"""Graph construction — upsert every entity/CDR/txn row with evidence.

Each edge carries `evidence_source` (exact FIR paragraph / CDR row /
transaction row) + `confidence_score`, making edges explainable and
click-through-to-evidence. Low-confidence merges surface as
PENDING_REVIEW edge status for human-in-the-loop sign-off.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from database import get_db, init_db
from graph_store import upsert_edge, upsert_entity
from models import EntityNode, EvidenceEdge

from .extract import extract_from_text, split_paragraphs
from .resolve import EntityResolver

FIR_CONF, CDR_CONF, TXN_CONF = 0.85, 0.92, 0.88


def _ensure_case(case_id: str, title: str = "Ingested case"):
    init_db()
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO cases (id, title, description, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (case_id, title, "Phase-2 ingestion", "OPEN",
             datetime.now(timezone.utc).isoformat()))


def _flush_canonical(resolver: EntityResolver, case_id: str):
    for c in resolver.canonicals:
        upsert_entity(EntityNode(id=c.key, name=c.name, aliases=c.aliases,
                                 phone_numbers=sorted(c.phones),
                                 entity_type=c.entity_type, base_risk_score=50.0), case_id)


def _persist(c, case_id: str):
    upsert_entity(EntityNode(id=c.key, name=c.name, aliases=c.aliases,
                             phone_numbers=sorted(c.phones),
                             entity_type=c.entity_type, base_risk_score=50.0), case_id)


def _add_evidence_row(edge_id: str, source_type: str, reference: str, details: str):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO evidence_sources (edge_id, source_type, reference, details)
               VALUES (?, ?, ?, ?)""", (edge_id, source_type, reference, details))


def ingest_firs(firs: list[dict], case_id: str, resolver: EntityResolver,
                model: str = "en_core_web_sm") -> dict:
    stats = Counter()
    for fir in firs:
        fir_no = fir.get("fir_no", "FIR-?")
        text = fir.get("text", fir.get("summary", ""))
        for pi, para in enumerate(split_paragraphs(text)):
            ext = extract_from_text(para, model)
            ctx = {fir_no, *ext.locations, *ext.orgs}
            for name in ext.persons:
                res = resolver.resolve(name, ext.phones, ext.vehicles, ctx, "PERSON")
                stats["person_mentions"] += 1
                if res.needs_review:
                    stats["pending_review"] += 1
            for loc in ext.locations:
                resolver.resolve(loc, contexts={fir_no}, entity_type="LOCATION")
                stats["locations"] += 1
            for org in ext.orgs:
                resolver.resolve(org, contexts={fir_no}, entity_type="ORG")
                stats["orgs"] += 1
            # co-mention edges between persons in the same paragraph (explainable)
            persons = [resolver.resolve(p, ext.phones, ext.vehicles, ctx).canonical
                       for p in ext.persons]
            seen = []
            for c in persons:
                if c.key not in seen:
                    seen.append(c.key)
            for i in range(len(seen)):
                for j in range(i + 1, len(seen)):
                    for _c in resolver.canonicals:
                        _persist(_c, case_id)
                    eid = f"{fir_no}:P{pi}:{seen[i]}->{seen[j]}"
                    upsert_edge(EvidenceEdge(
                        source_id=seen[i], target_id=seen[j], relation_type="CO_MENTIONED",
                        confidence_score=FIR_CONF,
                        evidence_source=f"{fir_no} para {pi}: {para[:220]}"),
                        case_id, link_id=eid,
                        status="PENDING_REVIEW" if stats["pending_review"] else "PENDING")
                    _add_evidence_row(eid, "FIR", f"{fir_no}#para{pi}", para)
                    stats["fir_edges"] += 1
    _flush_canonical(resolver, case_id)
    return dict(stats)


def _phone_node(resolver: EntityResolver, phone: str) -> CanonicalEntity:
    for c in resolver.canonicals:
        if phone in c.phones:
            return c
    return resolver._new(phone, [phone], [], {phone}, "PERSON")


def ingest_cdrs(cdrs: list[dict], case_id: str, resolver: EntityResolver) -> dict:
    stats = Counter()
    for row in cdrs:
        caller, callee = row.get("caller", ""), row.get("callee", "")
        if not caller or not callee:
            continue
        a, b = _phone_node(resolver, caller), _phone_node(resolver, callee)
        _persist(a, case_id); _persist(b, case_id)
        ref = row.get("id", f"{caller}->{callee}@{row.get('timestamp', '')}")
        eid = f"CDR:{ref}:{a.key}->{b.key}"
        upsert_edge(EvidenceEdge(
            source_id=a.key, target_id=b.key, relation_type="CALLED",
            confidence_score=CDR_CONF,
            evidence_source=f"CDR {ref}: {caller} -> {callee} "
                            f"({row.get('duration_sec', '?')}s @ {row.get('timestamp', '')})"),
            case_id, link_id=eid)
        _add_evidence_row(eid, "CDR", ref, json.dumps(row, default=str))
        stats["cdr_edges"] += 1
    _flush_canonical(resolver, case_id)
    return dict(stats)


def _acct_node(resolver: EntityResolver, acct: str) -> CanonicalEntity:
    for c in resolver.canonicals:
        if c.name == acct:
            return c
    return resolver._new(acct, [], [], {acct}, "BANK_ACCOUNT")


def ingest_transactions(txns: list[dict], case_id: str, resolver: EntityResolver) -> dict:
    stats = Counter()
    for row in txns:
        src = row.get("from_acct") or row.get("from", "")
        dst = row.get("to_acct") or row.get("to", "")
        if not src or not dst:
            continue
        a, b = _acct_node(resolver, src), _acct_node(resolver, dst)
        _persist(a, case_id); _persist(b, case_id)
        ref = row.get("id", f"{src}->{dst}")
        amt = row.get("amount", row.get("amount_inr", "?"))
        eid = f"TXN:{ref}:{a.key}->{b.key}"
        upsert_edge(EvidenceEdge(
            source_id=a.key, target_id=b.key, relation_type="SUSPICIOUS_TRANSFER",
            confidence_score=TXN_CONF,
            evidence_source=f"TXN {ref}: {src} -> {dst} Rs.{amt} @ "
                            f"{row.get('timestamp', row.get('date', ''))}"),
            case_id, link_id=eid)
        _add_evidence_row(eid, "BANK_TXN", ref, json.dumps(row, default=str))
        stats["txn_edges"] += 1
    _flush_canonical(resolver, case_id)
    return dict(stats)


def ingest_synthetic_dir(synth_dir: str | Path, case_id: str,
                         model: str = "en_core_web_sm") -> dict:
    """Full pipeline: fixtures/synthetic -> SQLite graph. Returns summary."""
    d = Path(synth_dir)
    _ensure_case(case_id)
    resolver = EntityResolver()

    def load(name: str) -> list[dict]:
        p = d / name
        if p.suffix == ".csv":
            with open(p, newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))
        return json.loads(p.read_text(encoding="utf-8"))

    firs = load("firs.json") if (d / "firs.json").exists() else load("firs.csv")
    cdrs = load("cdrs.json") if (d / "cdrs.json").exists() else load("cdrs.csv")
    txns = (load("transactions.json") if (d / "transactions.json").exists()
            else load("transactions.csv"))
    summary: dict = {"case_id": case_id}
    summary.update(ingest_firs(firs, case_id, resolver, model))
    summary.update(ingest_cdrs(cdrs, case_id, resolver))
    summary.update(ingest_transactions(txns, case_id, resolver))
    summary["entities"] = len(resolver.canonicals)
    summary["pending_review_items"] = list(resolver.pending_review[:50])
    summary["pending_review_count"] = len(resolver.pending_review)
    # Phase 3: replace hardcoded base_risk_score=50.0 with computed centrality
    # + anomaly scores (PageRank, betweenness, money cycles, burner clusters).
    try:
        from analytics import recompute_base_risk_scores
        summary["computed_base_risk"] = recompute_base_risk_scores(case_id)
    except Exception as exc:  # never fail ingestion on analytics
        summary["computed_base_risk_error"] = str(exc)
    return summary
