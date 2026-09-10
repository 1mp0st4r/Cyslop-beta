"""F1 Entity Resolution Engine — deterministic, explainable, idempotent.

Pre-work findings (mandatory verification, 2026-09-09):
- Storage reality: SQLite + NetworkX in-process graph (see
  [`database.py`](database.py:1) + [`graph_store.py`](graph_store.py:1)).
  README mentions Neo4j + a SQLite volume, but no Neo4j driver is imported
  anywhere; `graph_store.build_graph()` rebuilds a NetworkX DiGraph from the
  `entities`/`edges` SQLite rows on demand. NO migration performed (out of
  scope); F1 builds on SQLite rows + NetworkX.
- Entity creation today: `ingestion/build_graph.py:ingest_*` resolves mentions
  via `ingestion/resolve.py:EntityResolver` (anchor + rapidfuzz fuzzy, thresholds
  90/75) then persists via `graph_store.upsert_entity/upsert_edge`. Node labels
  are `entity_type` strings (PERSON/BANK_ACCOUNT/VEHICLE/LOCATION/ORG), props are
  (id/case_id/name/aliases JSON/phone_numbers JSON/entity_type/base_risk_score).
- SQLite tables created by `database.init_db()` execscript (cases/entities/edges/
  evidence_sources/audit_log/users). F1 appends `merge_log` via MERGE_LOG_SQL.
- `risk_engine.py` has nothing resolution-related (pure ISO 27005 scoring).
- Existing `ingestion/resolve.py` uses slightly different thresholds/rules than
  the F1 contract below; it is left untouched. F1's canonical R1–R5 live here so
  F6/F7 can cite stable rule ids.

Contracts locked for downstream features:
- ENTITY_TYPES taxonomy lives in models.py; rules R1–R5 ids + confidence values
  below are citable by F6/F7. Review queue rows live in `merge_log` with
  decision='pending' (queued) vs 'auto' (merged).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from database import ensure_merge_log_table, get_db, init_db
from models import CanonicalEntity, SourceRef

try:
    from rapidfuzz import fuzz as _fuzz

    def _token_set_ratio(a: str, b: str) -> float:
        return float(_fuzz.token_set_ratio(a, b))
except ImportError:  # offline fallback
    import difflib

    def _token_set_ratio(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100


HONORIFICS = {"shri", "smt", "smti", "dr", "md", "mohammad", "mohd", "mr", "mrs",
              "ms", "sri", "shree", "late", "adv", "prof"}

RULE_CONFIDENCE = {
    "exact_anchor+name": 0.95,   # R1
    "vehicle_anchor+name": 0.90,  # R2
    "review_candidate": 0.0,      # R3/R5 placeholder (no merge)
}


def normalize_phone(raw: str | None) -> str:
    """Strip +91/spaces/dashes -> 10 digits; return '' if not a valid 10-digit."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 else ""


def canonical_phone(raw: str | None) -> str:
    d = normalize_phone(raw)
    return f"+91-{d}" if d else ""


def normalize_vehicle(raw: str | None) -> str:
    if not raw:
        return ""
    v = re.sub(r"[\s\-_]", "", raw.upper())
    return v


def normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    toks = re.sub(r"[.]", " ", raw.lower()).split()
    toks = [t for t in toks if t not in HONORIFICS]
    return " ".join(toks)


def expand_initials(name: str) -> list[str]:
    """Token-level pre-pass: 'R. Kumar' -> variants ['r kumar', 'ramesh kumar'-agnostic].

    We cannot know what 'R' stands for, so we emit the initial as its own token
    AND a version with the initial dropped. rapidfuzz token_set_ratio then matches
    'r kumar' against 'ramesh kumar' on the shared 'kumar' token set. This is a
    pre-pass, not a custom scorer.
    """
    norm = normalize_name(name)
    if not norm:
        return [""]
    toks = norm.split()
    variants = {norm}
    # drop single-char tokens -> surname-only variant
    dropped = " ".join(t for t in toks if len(t) > 1)
    if dropped:
        variants.add(dropped)
    return sorted(variants)


def name_similarity(a: str, b: str) -> float:
    """Max token_set_ratio over initial-expansion variants (0-100)."""
    best = 0.0
    for va in expand_initials(a):
        for vb in expand_initials(b):
            if not va or not vb:
                continue
            s = _token_set_ratio(va, vb)
            if s > best:
                best = s
    # Initial-expansion rule (token-level pre-pass): "R. Kumar" vs "Ramesh Kumar"
    # shares surname + first-initial match -> count as strong match (>=85 for R1).
    # This is checked on tokens, not via a custom scorer.
    ta, tb = _name_tokens(a), _name_tokens(b)
    if ta and tb and ta[-1] == tb[-1]:
        fa, fb = ta[0], tb[0]
        if (len(fa) == 1 and fb.startswith(fa)) or (len(fb) == 1 and fa.startswith(fb)):
            best = max(best, 90.0)
    return best


def _name_tokens(name: str) -> list[str]:
    return [t for t in normalize_name(name).split() if t]


def deterministic_merge_id(survivor_id: str, merged_ids: list[str], rule: str) -> str:
    key = "|".join([survivor_id, *sorted(merged_ids), rule])
    return f"MERGE-{hashlib.sha256(key.encode()).hexdigest()[:12].upper()}"


def classify_pair(name_a: str, phones_a: list[str], vehicles_a: list[str],
                  name_b: str, phones_b: list[str], vehicles_b: list[str]) -> tuple[str, float]:
    """Apply R1–R5 in order. Returns (decision, confidence).

    decision in {"auto_r1", "auto_r2", "review_r3", "separate_r4", "review_r5", "no_match"}.
    """
    pa = {normalize_phone(p) for p in (phones_a or [])} - {""}
    pb = {normalize_phone(p) for p in (phones_b or [])} - {""}
    shared_phone = bool(pa & pb)
    va = {normalize_vehicle(v) for v in (vehicles_a or [])} - {""}
    vb = {normalize_vehicle(v) for v in (vehicles_b or [])} - {""}
    shared_vehicle = bool(va & vb)
    sim = name_similarity(name_a or "", name_b or "")

    if shared_phone and sim >= 85:
        return "auto_r1", 0.95  # R1
    if shared_vehicle and sim >= 85:
        return "auto_r2", 0.90  # R2
    if shared_phone and 60 <= sim < 85:
        return "review_r3", 0.0  # R3
    if shared_phone:
        return "separate_r4", 0.0  # R4 — burner hub; never merge, link via USES edges
    ta, tb = _name_tokens(name_a or ""), _name_tokens(name_b or "")
    if len(ta) >= 2 and len(tb) >= 2 and sim >= 95:
        return "review_r5", 0.0  # R5 — name-only, never auto
    return "no_match", 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_log_exists(merge_id: str) -> bool:
    ensure_merge_log_table()
    with get_db() as conn:
        return conn.execute("SELECT 1 FROM merge_log WHERE id=?", (merge_id,)).fetchone() is not None


def _write_merge_log(merge_id: str, survivor: str, merged: list[str], rule: str,
                     conf: float, evidence: list[dict], decision: str,
                     decided_by: str = "system") -> None:
    ensure_merge_log_table()
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO merge_log
               (id, surviving_entity_id, merged_entity_ids, rule, confidence,
                evidence, decision, decided_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (merge_id, survivor, json.dumps(merged), rule, conf,
             json.dumps(evidence), decision, decided_by, _now()))


def _entity_row(entity_id: str) -> dict | None:
    with get_db() as conn:
        r = conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        return dict(r) if r else None


def merge_entities(survivor_id: str, merged_ids: list[str], rule: str,
                   confidence: float, evidence: list[dict],
                   decided_by: str = "system",
                   decision: str = "auto") -> str:
    """Idempotent merge: re-point edges, union aliases/phones, delete losers.

    Stores full snapshots of removed entities + moved edges inside merge_log.evidence
    so `unmerge()` can restore without a DB rebuild. Safe to re-run.
    """
    init_db()
    merged_ids = [m for m in merged_ids if m != survivor_id]
    if not merged_ids:
        return deterministic_merge_id(survivor_id, [], rule)
    merge_id = deterministic_merge_id(survivor_id, merged_ids, rule)
    if _merge_log_exists(merge_id):
        return merge_id  # idempotent
    surv = _entity_row(survivor_id)
    if surv is None:
        raise ValueError(f"survivor {survivor_id} not found")
    snapshots, moved_edges = [], []
    aliases: set[str] = set(json.loads(surv["aliases"] or "[]"))
    phones: set[str] = set(json.loads(surv["phone_numbers"] or "[]"))
    names = [surv["name"]]
    with get_db() as conn:
        for mid in merged_ids:
            row = conn.execute("SELECT * FROM entities WHERE id=?", (mid,)).fetchone()
            if row is None:
                continue
            d = dict(row)
            snapshots.append({"entity": d,
                              "edges": [dict(r) for r in conn.execute(
                                  "SELECT * FROM edges WHERE source_id=? OR target_id=?",
                                  (mid, mid)).fetchall()]})
            names.append(d["name"])
            aliases.add(d["name"])
            aliases.update(json.loads(d["aliases"] or "[]"))
            phones.update(json.loads(d["phone_numbers"] or "[]"))
        # canonical_name: longest/most frequent variant
        counts = Counter(names)
        canon = sorted(counts, key=lambda n: (counts[n], len(n or "")))[-1]
        aliases.discard(canon)
        conn.execute("UPDATE entities SET name=?, aliases=?, phone_numbers=? WHERE id=?",
                     (canon, json.dumps(sorted(aliases)), json.dumps(sorted(phones)), survivor_id))
        # re-point edges (deterministic new ids to stay idempotent)
        for snap in snapshots:
            for e in snap["edges"]:
                ns = survivor_id if e["source_id"] in merged_ids else e["source_id"]
                nt = survivor_id if e["target_id"] in merged_ids else e["target_id"]
                if ns == nt:
                    continue  # drop self-loop created by merge
                new_id = f"{e['id']}::merged->{survivor_id}"
                moved_edges.append({"old_id": e["id"], "new_id": new_id})
                conn.execute(
                    """INSERT OR IGNORE INTO edges
                       (id, case_id, source_id, target_id, relation_type, confidence_score,
                        evidence_source, status, reviewer, reviewed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (new_id, e["case_id"], ns, nt, e["relation_type"], e["confidence_score"],
                     e["evidence_source"], e["status"], e["reviewer"], e["reviewed_at"]))
                conn.execute("DELETE FROM edges WHERE id=?", (e["id"],))
        for snap in snapshots:
            conn.execute("DELETE FROM entities WHERE id=?", (snap["entity"]["id"],))
        try:
            conn.execute(
                "UPDATE entity_sources SET entity_id=? WHERE entity_id IN (%s)" % ",".join("?" * len(merged_ids)) if merged_ids else "SELECT 1",
                (survivor_id, *merged_ids) if merged_ids else ())
        except Exception:
            pass
    full_evidence = {"trigger": evidence, "snapshots": snapshots, "moved_edges": moved_edges}
    _write_merge_log(merge_id, survivor_id, merged_ids, rule, confidence,
                     [full_evidence] if isinstance(full_evidence, dict) else full_evidence,
                     decision, decided_by)
    # fix evidence payload shape: store dict directly
    with get_db() as conn:
        conn.execute("UPDATE merge_log SET evidence=? WHERE id=?",
                     (json.dumps(full_evidence), merge_id))
    return merge_id


def queue_review(entity_a: str, entity_b: str, rule: str, score: float,
                 evidence: list[dict]) -> str:
    """Queue a borderline candidate without merging. Idempotent."""
    init_db()
    survivor, merged = sorted([entity_a, entity_b])[0], sorted([entity_a, entity_b])[1:]
    merge_id = deterministic_merge_id(f"REVIEW-{survivor}", merged, rule)
    if _merge_log_exists(merge_id):
        return merge_id
    _write_merge_log(merge_id, survivor, merged, rule, round(float(score) / 100, 3),
                     evidence, "pending", "system")
    return merge_id


def resolve_case(case_id: str) -> dict:
    """Run R1–R5 over all PERSON entities in a case. Idempotent."""
    init_db()
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM entities WHERE case_id=? ORDER BY id", (case_id,)).fetchall()]
    persons = [r for r in rows if str(r.get("entity_type", "")).upper() == "PERSON"]
    # Blocking: group by normalized phone / vehicle / name-token
    auto_merges: list[str] = []
    queued: list[str] = []
    uses_edges = 0
    # pairwise within blocks only
    def block_key(r: dict) -> set[str]:
        keys = set()
        for p in json.loads(r.get("phone_numbers") or "[]"):
            d = normalize_phone(p)
            if d:
                keys.add(f"ph:{d}")
        for tok in _name_tokens(r.get("name", "")):
            keys.add(f"nm:{tok}")
        return keys

    blocks: dict[str, list[dict]] = {}
    for r in persons:
        for k in block_key(r):
            blocks.setdefault(k, []).append(r)
    seen_pairs: set[tuple[str, str]] = set()
    for members in blocks.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                pair = tuple(sorted([a["id"], b["id"]]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                # skip if either no longer exists (merged earlier this run)
                if _entity_row(a["id"]) is None or _entity_row(b["id"]) is None:
                    continue
                dec, conf = classify_pair(
                    a["name"], json.loads(a["phone_numbers"] or "[]"), [],
                    b["name"], json.loads(b["phone_numbers"] or "[]"), [])
                ev = [{"a": a["id"], "b": b["id"], "a_name": a["name"], "b_name": b["name"]}]
                if dec == "auto_r1":
                    survivor = sorted([a["id"], b["id"]])[0]
                    loser = b["id"] if survivor == a["id"] else a["id"]
                    auto_merges.append(merge_entities(survivor, [loser], "exact_anchor+name", conf, ev))
                    # refresh local copies
                    for idx, holder in enumerate((a, b)):
                        fresh = _entity_row(holder["id"])
                        if fresh:
                            members[i if holder is a else j] = fresh
                elif dec == "auto_r2":
                    survivor = sorted([a["id"], b["id"]])[0]
                    loser = b["id"] if survivor == a["id"] else a["id"]
                    auto_merges.append(merge_entities(survivor, [loser], "vehicle_anchor+name", conf, ev))
                elif dec in ("review_r3", "review_r5"):
                    rule = "review_candidate"
                    queued.append(queue_review(a["id"], b["id"], rule,
                                               name_similarity(a["name"], b["name"]), ev))
                elif dec == "separate_r4":
                    # R4: keep separate; ensure person->phone USES edges exist (idempotent)
                    for ent in (a, b):
                        for p in json.loads(ent["phone_numbers"] or "[]"):
                            d = normalize_phone(p)
                            if not d:
                                continue
                            phone_id = f"PHONE-{d}"
                            with get_db() as conn:
                                prow = conn.execute("SELECT id FROM entities WHERE id=?",
                                                    (phone_id,)).fetchone()
                                if prow is None:
                                    conn.execute(
                                        """INSERT OR IGNORE INTO entities
                                           (id, case_id, name, aliases, phone_numbers, entity_type, base_risk_score)
                                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                        (phone_id, case_id, canonical_phone(p), "[]",
                                         json.dumps([canonical_phone(p)]), "PHONE", 0.0))
                                eid = f"USES:{ent['id']}->{phone_id}"
                                conn.execute(
                                    """INSERT OR IGNORE INTO edges
                                       (id, case_id, source_id, target_id, relation_type,
                                        confidence_score, evidence_source, status)
                                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                    (eid, case_id, ent["id"], phone_id, "USES", 0.9,
                                     f"Shared handset {canonical_phone(p)} (R4 burner-hub guard)", "CONFIRMED"))
                                uses_edges += 1
    return {"case_id": case_id, "auto_merges": auto_merges,
            "auto_merge_count": len(auto_merges), "queued": queued,
            "queued_count": len(queued), "uses_edges_ensured": uses_edges}


def list_pending_reviews() -> list[dict]:
    ensure_merge_log_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM merge_log WHERE decision='pending' ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["merged_entity_ids"] = json.loads(d["merged_entity_ids"] or "[]")
        try:
            d["evidence"] = json.loads(d["evidence"] or "[]")
        except (ValueError, TypeError):
            pass
        out.append(d)
    return out


def decide_review(merge_id: str, action: str, decided_by: str) -> dict:
    """Accept (perform merge) or reject a queued candidate. Idempotent."""
    ensure_merge_log_table()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM merge_log WHERE id=?", (merge_id,)).fetchone()
        if row is None:
            raise ValueError("review id not found")
        d = dict(row)
    if d["decision"] in ("accepted", "rejected"):
        return {"id": merge_id, "decision": d["decision"], "deduped": True}
    if action == "accepted":
        merged = json.loads(d["merged_entity_ids"] or "[]")
        ev = json.loads(d["evidence"] or "[]")
        # perform the actual merge now (new deterministic id), mark review accepted
        try:
            new_id = merge_entities(d["surviving_entity_id"], merged, d["rule"] or "review_candidate",
                                    float(d["confidence"] or 0.8), ev if isinstance(ev, list) else [ev],
                                    decided_by, decision="accepted")
        except ValueError:
            new_id = merge_id
        with get_db() as conn:
            conn.execute("UPDATE merge_log SET decision='accepted', decided_by=? WHERE id=?",
                         (decided_by, merge_id))
        return {"id": merge_id, "merged_as": new_id, "decision": "accepted"}
    with get_db() as conn:
        conn.execute("UPDATE merge_log SET decision='rejected', decided_by=? WHERE id=?",
                     (decided_by, merge_id))
    return {"id": merge_id, "decision": "rejected"}


def unmerge(merge_id: str) -> dict:
    """Reverse any merge using merge_log evidence snapshots. Idempotent."""
    ensure_merge_log_table()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM merge_log WHERE id=?", (merge_id,)).fetchone()
        if row is None:
            raise ValueError("merge id not found")
        d = dict(row)
    try:
        payload = json.loads(d["evidence"] or "{}")
    except (ValueError, TypeError):
        payload = {}
    snapshots = payload.get("snapshots", []) if isinstance(payload, dict) else []
    moved = payload.get("moved_edges", []) if isinstance(payload, dict) else []
    if not snapshots:
        return {"id": merge_id, "restored": [], "note": "no snapshots; nothing to restore"}
    with get_db() as conn:
        restored = []
        for snap in snapshots:
            ent = snap.get("entity", {})
            if ent and conn.execute("SELECT 1 FROM entities WHERE id=?",
                                    (ent["id"],)).fetchone() is None:
                conn.execute(
                    """INSERT OR IGNORE INTO entities
                       (id, case_id, name, aliases, phone_numbers, entity_type, base_risk_score)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (ent["id"], ent["case_id"], ent["name"], ent["aliases"],
                     ent["phone_numbers"], ent["entity_type"], ent["base_risk_score"]))
                restored.append(ent["id"])
            for e in snap.get("edges", []):
                conn.execute(
                    """INSERT OR IGNORE INTO edges
                       (id, case_id, source_id, target_id, relation_type, confidence_score,
                        evidence_source, status, reviewer, reviewed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (e["id"], e["case_id"], e["source_id"], e["target_id"], e["relation_type"],
                     e["confidence_score"], e["evidence_source"], e.get("status", "PENDING"),
                     e.get("reviewer", ""), e.get("reviewed_at", "")))
        for m in moved:
            conn.execute("DELETE FROM edges WHERE id=?", (m.get("new_id"),))
        conn.execute("UPDATE merge_log SET decision='rejected', decided_by='unmerge' WHERE id=?",
                     (merge_id,))
    return {"id": merge_id, "restored": restored, "removed_repointed": len(moved)}


def ingest_canonical(canonical: CanonicalEntity, case_id: str) -> dict:
    """Idempotent ingestion path for a CanonicalEntity: upsert + resolve.

    Deterministic node id: PHONE-*/VEH-* for anchor types, else content hash so
    re-running the same input never duplicates nodes/edges/findings.
    """
    from graph_store import upsert_entity
    from models import EntityNode
    init_db()
    attrs = canonical.attributes or {}
    phones = [str(p) for p in attrs.get("phones", attrs.get("phone_numbers", []))]
    vehicles = [str(v) for v in attrs.get("vehicles", [])]
    if canonical.type == "phone":
        node_id = f"PHONE-{normalize_phone(canonical.canonical_name or '')}"
        name = canonical_phone(canonical.canonical_name or "")
        etype, ph = "PHONE", [name]
    elif canonical.type == "vehicle":
        node_id = f"VEH-{normalize_vehicle(canonical.canonical_name or '')}"
        name, etype, ph = normalize_vehicle(canonical.canonical_name or ""), "VEHICLE", []
    else:
        h = hashlib.sha256(
            f"{case_id}|{canonical.type}|{normalize_name(canonical.canonical_name or '')}|"
            f"{sorted(phones)}|{sorted(vehicles)}".encode()).hexdigest()[:10].upper()
        node_id = canonical.id if canonical.id else f"ENT-{h}"
        name = canonical.canonical_name or node_id
        etype = {"person": "PERSON", "location": "LOCATION",
                 "organization": "ORG"}.get(canonical.type, "PERSON")
        ph = [canonical_phone(p) for p in phones if normalize_phone(p)]
    upsert_entity(EntityNode(id=node_id, name=name, aliases=[],
                             phone_numbers=ph, entity_type=etype,
                             base_risk_score=float(attrs.get("base_risk_score", 50.0))), case_id)
    try:
        from database import ensure_entity_sources_table as _ensure_src
        _ensure_src()
        with get_db() as _conn:
            for _sr in (canonical.source_refs or []):
                _span = _sr.span if isinstance(_sr.span, (list, tuple)) else [None, None]
                _ss = _span[0] if len(_span) > 0 else None
                _se = _span[1] if len(_span) > 1 else None
                _exists = _conn.execute(
                    "SELECT 1 FROM entity_sources WHERE entity_id=? AND source_type=? AND record_id=? AND (span_start IS ? OR span_start=?) AND (span_end IS ? OR span_end=?)",
                    (node_id, _sr.source_type, _sr.record_id, _ss, _ss, _se, _se)).fetchone()
                if _exists is None:
                    _conn.execute(
                        "INSERT INTO entity_sources (entity_id, case_id, source_type, record_id, field, span_start, span_end, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (node_id, case_id, _sr.source_type, _sr.record_id, _sr.field, _ss, _se, _sr.confidence))
    except Exception:
        pass
    result = resolve_case(case_id)
    result["node_id"] = node_id
    return result


def get_entity_detail(entity_id: str) -> dict:
    from database import ensure_entity_sources_table as _ensure_src
    init_db()
    _ensure_src()
    row = _entity_row(entity_id)
    if row is None:
        raise ValueError("entity not found")
    with get_db() as conn:
        srcs = [dict(r) for r in conn.execute(
            "SELECT source_type, record_id, field, span_start, span_end, confidence, case_id FROM entity_sources WHERE entity_id=? ORDER BY id",
            (entity_id,)).fetchall()]
        hist = [dict(r) for r in conn.execute(
            "SELECT * FROM merge_log WHERE surviving_entity_id=? OR merged_entity_ids LIKE ? ORDER BY created_at",
            (entity_id, "%" + entity_id + "%")).fetchall()]
    for h in hist:
        try:
            h["merged_entity_ids"] = json.loads(h["merged_entity_ids"] or "[]")
        except (ValueError, TypeError):
            pass
    refs = [{"source_type": s["source_type"], "record_id": s["record_id"], "field": s["field"],
             "span": [s["span_start"], s["span_end"]] if s["span_start"] is not None else None,
             "confidence": s["confidence"]} for s in srcs]
    return {"entity": row, "source_refs": refs, "merge_history": hist}


def list_pending_reviews_for_case(case_id: str) -> list[dict]:
    out = []
    for r in list_pending_reviews():
        erow = _entity_row(r.get("surviving_entity_id", ""))
        if erow and erow.get("case_id") == case_id:
            out.append(r)
    return out
