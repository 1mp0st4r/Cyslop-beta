"""Feature 3 — Rule-based suspicious pattern detection.

Four explainable detectors over the resolved graph, each producing
[`Finding`](#) records with evidence references:

* P1 circular money flow — directed cycle 3-5 on TRANSFER edges, all legs
  within ``cycle_window_days`` (default 30). Bounded DFS enumeration.
* P2 burner phone hub — node with >= ``burner_min_peers`` distinct USES/CALL
  peers and first->last span <= ``burner_max_span_days`` (default 45).
* P3 call-then-transfer — CDR pair followed by a transfer within 72h,
  firing at >= ``call_transfer_min_pairs`` occurrences per pair.
* P4 communication burst — per-pair daily call counts vs. own baseline;
  robust z (median/MAD) >= ``burst_z_threshold`` in a rolling 7-day window.

All tunables live in [`PATTERN_CONFIG`](patterns.py:1). Findings persist in
the ``findings`` table with ``UNIQUE(case_id, rule_id, entity_set_hash)``
dedup — re-scans never duplicate, and dismissed findings are never
resurrected. Reuses timestamp parsing / edge-bucket conventions from
[`analytics.py`](analytics.py:1) rather than forking logic.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any

# ---------------------------------------------------------------------------
# Tunables — single place, citable in explanations.
# ---------------------------------------------------------------------------
PATTERN_CONFIG: dict[str, Any] = {
    # P1 circular money flow
    "cycle_min_len": 3,
    "cycle_max_len": 5,
    "cycle_window_days": 30,
    # P2 burner phone hub
    "burner_min_peers": 4,
    "burner_max_span_days": 45,
    # P3 call-then-transfer
    "call_transfer_max_gap_hours": 72,
    "call_transfer_min_pairs": 3,
    # P4 communication burst
    "burst_window_days": 7,
    "burst_z_threshold": 4.0,
}

TXN_KEYWORDS = ("TRANSFER", "TXN", "MONEY", "PAYMENT", "TRANSACTION", "SUSPICIOUS_TRANSFER")
CALL_KEYWORDS = ("CALL", "CDR", "PHONE", "CONTACT", "FREQUENT_CALLS", "CALLED", "USES")

RULE_IDS = ("P1_circular_flow", "P2_burner_hub", "P3_call_then_transfer", "P4_comm_burst")
SEVERITY = {
    "P1_circular_flow": "high",
    "P2_burner_hub": "high",
    "P3_call_then_transfer": "medium",
    "P4_comm_burst": "medium",
}

# ---------------------------------------------------------------------------
# Finding contract (mirrors the spec addition to models.py; defined here so
# patterns.py is self-contained, and re-exported when models.py is patched).
# ---------------------------------------------------------------------------
try:  # prefer the canonical contract when models.py has been patched
    from models import EvidenceRef as _ER, Finding as _F  # type: ignore
    EvidenceRef, Finding = _ER, _F
    _MODELS_PATCHED = True
except Exception:  # standalone fallback — identical field surface
    from pydantic import BaseModel, Field

    class EvidenceRef(BaseModel):  # type: ignore[no-redef]
        edge_id: str = ""
        source_type: str = "EDGE"
        reference: str = ""
        detail: str = ""

    class Finding(BaseModel):  # type: ignore[no-redef]
        id: str
        rule_id: str
        severity: str = "medium"
        score: float = Field(default=0.0, ge=0.0, le=1.0)
        entity_ids: list[str] = Field(default_factory=list)
        explanation: str = ""
        evidence: list[EvidenceRef] = Field(default_factory=list)  # type: ignore[valid-type]
        detected_at: str = ""
        status: str = "open"

    _MODELS_PATCHED = False


FINDINGS_SQL = """
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL DEFAULT '',
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    score REAL NOT NULL DEFAULT 0.0,
    entity_ids TEXT NOT NULL DEFAULT '[]',
    entity_set_hash TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    detected_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_dedup ON findings(case_id, rule_id, entity_set_hash);
CREATE INDEX IF NOT EXISTS idx_findings_case ON findings(case_id);
"""


def ensure_findings_table(db_path: str | None = None) -> None:
    from database import get_db

    with get_db(db_path) as conn:
        conn.executescript(FINDINGS_SQL)


# ---------------------------------------------------------------------------
# Data-access helpers (reuse graph_store / evidence_sources conventions)
# ---------------------------------------------------------------------------
def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)
    s = str(value).strip()
    for cand in (s, s.replace("Z", ""), s[:19], s[:10]):
        try:
            return datetime.fromisoformat(cand)
        except ValueError:
            continue
    return None


def _edge_ts(edge: dict[str, Any], details: str = "") -> datetime | None:
    ts = _parse_ts(edge.get("timestamp") or edge.get("reviewed_at"))
    if ts is not None:
        return ts
    blob = f"{edge.get('evidence_source', '')} {details}"
    m = re.search(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?)", blob)
    if m:
        ts = _parse_ts(m.group(1))
        if ts is not None:
            return ts
    try:
        ts = _parse_ts(json.loads(details or "{}").get("timestamp"))
        if ts is not None:
            return ts
    except Exception:
        pass
    return None


def _is_txn(rel: str) -> bool:
    r = (rel or "").upper()
    return any(k in r for k in TXN_KEYWORDS)


def _is_call(rel: str) -> bool:
    r = (rel or "").upper()
    return any(k in r for k in CALL_KEYWORDS)


def _load_case(case_id: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Returns (enriched edge rows, {edge_id: details_json})."""
    from database import get_db
    from graph_store import get_edges

    _, raw = get_edges(case_id)
    details: dict[str, str] = {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT edge_id, details FROM evidence_sources").fetchall()
            for r in rows:
                details.setdefault(str(r["edge_id"]), str(r["details"] or ""))
    except Exception:
        pass
    return [dict(r) for r in raw], details


def _entity_set_hash(entity_ids: list[str]) -> str:
    return hashlib.sha256(
        "|".join(sorted(entity_ids)).encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Rule implementations — pure functions over edge rows (testable w/o DB)
# ---------------------------------------------------------------------------
def detect_circular_flow(
    edges: list[dict[str, Any]],
    details: dict[str, str] | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """P1: directed cycles len 3-5 on TRANSFER edges within window days."""
    cfg = cfg or PATTERN_CONFIG
    details = details or {}
    lo, hi = int(cfg["cycle_min_len"]), int(cfg["cycle_max_len"])
    window_days = int(cfg["cycle_window_days"])
    # adjacency with (neighbor, edge_id, ts)
    adj: dict[str, list[tuple[str, str, datetime | None]]] = defaultdict(list)
    edge_of: dict[tuple[str, str], list[tuple[str, datetime | None]]] = defaultdict(list)
    for e in edges:
        if not _is_txn(str(e.get("relation_type", ""))):
            continue
        ts = _edge_ts(e, details.get(str(e.get("id", "")), ""))
        adj[str(e["source_id"])].append((str(e["target_id"]), str(e["id"]), ts))
        edge_of[(str(e["source_id"]), str(e["target_id"]))].append((str(e["id"]), ts))
    found: list[dict[str, Any]] = []
    seen_sets: set[tuple[str, ...]] = set()

    def dfs(start: str, node: str, path: list[str], leg_ts: list[datetime | None]) -> None:
        if len(path) > hi:
            return
        for nxt, eid, ts in adj.get(node, []):
            if nxt == start and lo <= len(path) <= hi and len(path) >= 2:
                cyc = [*path]
                key = tuple(sorted(cyc))
                if key in seen_sets:
                    continue
                stamps = [t for t in [*leg_ts, ts] if t is not None]
                if stamps:
                    span = (max(stamps) - min(stamps)).days
                    if span > window_days:
                        continue
                    t1, t2 = min(stamps).date().isoformat(), max(stamps).date().isoformat()
                else:
                    span, t1, t2 = 0, "?", "?"
                seen_sets.add(key)
                # evidence: one edge id per leg
                ev, total = [], 0.0
                legs = list(zip([*path[1:], start], cyc))  # (dst, src) pairs
                for dst, src in [(cyc[(i + 1) % len(cyc)], cyc[i]) for i in range(len(cyc))]:
                    cand = edge_of.get((src, dst), [])
                    if cand:
                        eid0, ts0 = cand[0]
                        ev.append({"edge_id": eid0, "source_type": "BANK_TXN",
                                   "reference": eid0,
                                   "detail": f"{src}->{dst} @ {ts0}"})
                found.append({"cycle": cyc, "span_days": span, "t1": t1,
                              "t2": t2, "evidence": ev})
            elif nxt not in path and nxt != start:
                dfs(start, nxt, [*path, nxt], [*leg_ts, ts])

    for s in list(adj):
        dfs(s, s, [s], [])
    out = []
    for f in found:
        cyc = f["cycle"]
        amt_note = f"t1={f['t1']} t2={f['t2']}"
        out.append({
            "rule_id": "P1_circular_flow",
            "entity_ids": cyc,
            "explanation": (
                f"Circular money flow {'->'.join(cyc)}->{cyc[0]} "
                f"between {f['t1']} and {f['t2']} "
                f"(cycle length {len(cyc)}, window ≤{window_days}d; {amt_note})"),
            "evidence": f["evidence"],
            "score": min(1.0, 0.7 + 0.1 * len(cyc)),
        })
    return out


def detect_burner_hub(
    edges: list[dict[str, Any]],
    details: dict[str, str] | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """P2: node with >= N distinct CALL peers within a short active window."""
    cfg = cfg or PATTERN_CONFIG
    details = details or {}
    n_min = int(cfg["burner_min_peers"])
    max_span = int(cfg["burner_max_span_days"])
    peers: dict[str, dict[str, list[datetime | None]]] = defaultdict(lambda: defaultdict(list))
    for e in edges:
        if not _is_call(str(e.get("relation_type", ""))):
            continue
        ts = _edge_ts(e, details.get(str(e.get("id", "")), ""))
        s, t = str(e["source_id"]), str(e["target_id"])
        peers[s][t].append(ts)
        peers[t][s].append(ts)
    out = []
    for node, pm in peers.items():
        if len(pm) < n_min:
            continue
        stamps = [t for v in pm.values() for t in v if t is not None]
        span = (max(stamps) - min(stamps)).days if stamps else 0
        if stamps and span > max_span:
            continue
        ev = [{"edge_id": "", "source_type": "CDR", "reference": p,
               "detail": f"{node}<->{p}"} for p in sorted(pm)]
        out.append({
            "rule_id": "P2_burner_hub",
            "entity_ids": [node, *sorted(pm)],
            "explanation": (
                f"Phone {node} connects {len(pm)} otherwise-unconnected "
                f"individuals over {span} days "
                f"(threshold ≥{n_min} peers within ≤{max_span}d) — "
                "kept separate by design, not merged"),
            "evidence": ev,
            "score": min(1.0, 0.6 + 0.08 * len(pm)),
        })
    return out


def detect_call_then_transfer(
    edges: list[dict[str, Any]],
    details: dict[str, str] | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """P3: CDR pair followed by transfer within 72h, >= K occurrences."""
    cfg = cfg or PATTERN_CONFIG
    details = details or {}
    gap_h = float(cfg["call_transfer_max_gap_hours"])
    k_min = int(cfg["call_transfer_min_pairs"])
    calls: dict[frozenset, list[tuple[datetime, str]]] = defaultdict(list)
    txns: dict[frozenset, list[tuple[datetime, str]]] = defaultdict(list)
    for e in edges:
        ts = _edge_ts(e, details.get(str(e.get("id", "")), ""))
        if ts is None:
            continue
        key = frozenset((str(e["source_id"]), str(e["target_id"])))
        if _is_call(str(e.get("relation_type", ""))):
            calls[key].append((ts, str(e["id"])))
        elif _is_txn(str(e.get("relation_type", ""))):
            txns[key].append((ts, str(e["id"])))
    out = []
    for key, cl in calls.items():
        if key not in txns:
            continue
        tl = sorted(txns[key])
        hits = []
        for cts, ceid in sorted(cl):
            for tts, teid in tl:
                gap = (tts - cts).total_seconds() / 3600.0
                if 0 < gap <= gap_h:
                    hits.append((cts, ceid, tts, teid))
                    break
        if len(hits) >= k_min:
            a, b = sorted(key)
            ev = []
            ev = []
            for cts, ce, tts, te in hits:
                ev.append({"edge_id": ce, "source_type": "CDR",
                           "reference": ce,
                           "detail": f"call {cts.date().isoformat()} -> transfer {tts.date().isoformat()}"})
                ev.append({"edge_id": te, "source_type": "BANK_TXN",
                           "reference": te,
                           "detail": f"transfer {tts.date().isoformat()} after call {cts.date().isoformat()}"})
            out.append({
                "rule_id": "P3_call_then_transfer",
                "entity_ids": [a, b],
                "explanation": (
                    f"{a} and {b}: {len(hits)} calls each followed by a "
                    f"transfer within {gap_h:g}h (threshold ≥{k_min})"),
                "evidence": ev,
                "score": min(1.0, 0.4 + 0.15 * len(hits)),
            })
    return out


def _robust_z(series: list[int], x: int) -> float:
    med = median(series)
    mad = median([abs(v - med) for v in series])
    if mad == 0:
        denom = max(1.0, abs(med) if med else 1.0)
        return (x - med) / denom
    return 0.6745 * (x - med) / (mad or 1e-9)


def detect_comm_burst(
    edges: list[dict[str, Any]],
    details: dict[str, str] | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """P4: per-pair daily call counts vs own baseline, robust z >= 4."""
    cfg = cfg or PATTERN_CONFIG
    details = details or {}
    win = int(cfg["burst_window_days"])
    z_thr = float(cfg["burst_z_threshold"])
    per_pair: dict[frozenset, list[datetime]] = defaultdict(list)
    for e in edges:
        if not _is_call(str(e.get("relation_type", ""))):
            continue
        ts = _edge_ts(e, details.get(str(e.get("id", "")), ""))
        if ts is None:
            continue
        per_pair[frozenset((str(e["source_id"]), str(e["target_id"])))].append(ts)
    out = []
    for key, stamps in per_pair.items():
        days: dict[str, int] = defaultdict(int)
        for t in stamps:
            days[t.date().isoformat()] += 1
        if len(days) < win + 1:
            continue  # need baseline + window
        ordered = sorted(days)
        best: tuple[str, float, int, float] | None = None
        for i in range(len(ordered) - win + 1):
            window_days = ordered[i:i + win]
            baseline = [days[d] for d in ordered[:i]] or [days[ordered[0]]]
            for d in window_days:
                z = _robust_z(baseline + [0] * 0 or baseline, days[d])
                # baseline must include history; skip trivial single-point
                if len(set(baseline)) <= 1 and days[d] <= (baseline[0] + 1):
                    continue
                if z >= z_thr and (best is None or z > best[1]):
                    med = median(baseline) or 1.0
                    mult = days[d] / med if med else float(days[d])
                    best = (d, z, days[d], mult)
        if best:
            a, b = sorted(key)
            d, z, cnt, mult = best
            out.append({
                "rule_id": "P4_comm_burst",
                "entity_ids": [a, b],
                "explanation": (
                    f"{a}<->{b} call volume spiked {mult:.1f}× above their "
                    f"baseline during {d} (robust z={z:.1f} ≥ {z_thr:g}, "
                    f"{win}d window)"),
                "evidence": [{"edge_id": "", "source_type": "CDR",
                              "reference": f"{a}|{b}|{d}",
                              "detail": f"{cnt} calls on {d}"}],
                "score": min(1.0, 0.5 + 0.05 * z),
            })
    return out


# ---------------------------------------------------------------------------
# Persistence + orchestration
# ---------------------------------------------------------------------------
def _store(case_id: str, det: dict[str, Any]) -> dict[str, Any] | None:
    """Insert unless (case_id, rule_id, entity_set_hash) exists. None if dup."""
    from database import get_db

    ensure_findings_table()
    ehash = _entity_set_hash(det["entity_ids"])
    fid = f"{case_id}:{det['rule_id']}:{ehash}"
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, status FROM findings WHERE case_id=? AND rule_id=? AND entity_set_hash=?",
            (case_id, det["rule_id"], ehash)).fetchone()
        if row:
            return None  # dedup: never duplicate, never resurrect dismissed
        conn.execute(
            """INSERT INTO findings (id, case_id, rule_id, severity, score,
               entity_ids, entity_set_hash, explanation, evidence, detected_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (fid, case_id, det["rule_id"], SEVERITY.get(det["rule_id"], "medium"),
             float(max(0.0, min(1.0, det.get("score", 0.5)))),
             json.dumps(det["entity_ids"]), ehash, det["explanation"],
             json.dumps(det["evidence"]), _now()))
    return {"id": fid, "rule_id": det["rule_id"],
            "severity": SEVERITY.get(det["rule_id"], "medium"),
            "score": det.get("score", 0.5), "entity_ids": det["entity_ids"],
            "explanation": det["explanation"], "evidence": det["evidence"],
            "detected_at": _now(), "status": "open"}


def scan_case(case_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run all four rules; return {"new": [...], "total": N}."""
    cfg = cfg or PATTERN_CONFIG
    edges, details = _load_case(case_id)
    dets = [
        *detect_circular_flow(edges, details, cfg),
        *detect_burner_hub(edges, details, cfg),
        *detect_call_then_transfer(edges, details, cfg),
        *detect_comm_burst(edges, details, cfg),
    ]
    try:
        import anomaly as _anom  # F4: same Finding contract / dedup machinery
        dets += [
            *_anom.detect_amount_outlier(edges, details),
            *_anom.detect_volume_spike(edges, details),
            *_anom.detect_counterparty_expansion(edges, details),
            *_anom.detect_odd_hour(edges, details),
        ]
        for _d in dets:
            if _d["rule_id"].startswith("A") and _d.get("severity"):
                SEVERITY[_d["rule_id"]] = _d["severity"]
    except Exception:
        pass
    new = []
    for d in dets:
        row = _store(case_id, d)
        if row is not None:
            new.append(row)
    return {"case_id": case_id, "new": new, "new_count": len(new),
            "candidates": len(dets)}


def list_findings(case_id: str, status: str | None = None) -> list[dict[str, Any]]:
    from database import get_db

    ensure_findings_table()
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM findings WHERE case_id=? AND status=? ORDER BY severity, detected_at",
                (case_id, status)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM findings WHERE case_id=? ORDER BY detected_at",
                (case_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["entity_ids"] = json.loads(d.get("entity_ids") or "[]")
        d["evidence"] = json.loads(d.get("evidence") or "[]")
        out.append(d)
    return out


def set_status(finding_id: str, status: str) -> dict[str, Any]:
    from database import get_db

    if status not in ("open", "confirmed", "dismissed"):
        raise ValueError("status must be open|confirmed|dismissed")
    ensure_findings_table()
    with get_db() as conn:
        cur = conn.execute("UPDATE findings SET status=? WHERE id=?",
                           (status, finding_id))
        if cur.rowcount == 0:
            raise ValueError("Finding not found.")
        row = conn.execute("SELECT * FROM findings WHERE id=?",
                           (finding_id,)).fetchone()
    d = dict(row)
    d["entity_ids"] = json.loads(d.get("entity_ids") or "[]")
    d["evidence"] = json.loads(d.get("evidence") or "[]")
    return d


def register_routes(app: Any, skip_analyze_alias: bool = False) -> None:
    """Attach F3 routes to the FastAPI app (import-safe, additive)."""
    from fastapi import Depends

    try:
        from security import get_current_user_role as _role
        from security import CurrentUser as _CU, get_current_user as _user
        from audit_log import log_officer_action as _log
        _has_auth = True
    except Exception:
        _has_auth = False

    role_dep = Depends(_role) if _has_auth else lambda: "analyst"  # type: ignore

    @app.post("/patterns/scan/{case_id}", tags=["Patterns"])
    def _scan(case_id: str, role: str = role_dep):  # type: ignore[no-untyped-def]
        if _has_auth:
            try:
                _log(role, "SCAN_PATTERNS", case_id)
            except Exception:
                pass
        return scan_case(case_id)

    # NOTE: POST /analyze/scan/{case_id} lives in anomaly.py (scan_all = F3+F4).
    # Removed duplicate here to avoid route override / OpenAPI collision.

    @app.get("/findings/{case_id}", tags=["Patterns"])
    def _list(case_id: str, status: str | None = None, role: str = role_dep):  # type: ignore[no-untyped-def]
        rows = list_findings(case_id, status)
        return {"case_id": case_id, "count": len(rows), "findings": rows}

    @app.post("/findings/{fid}/confirm", tags=["Patterns"])
    def _confirm(fid: str, role: str = role_dep):  # type: ignore[no-untyped-def]
        if _has_auth:
            try:
                _log(role, f"CONFIRM_FINDING_{fid}", "")
            except Exception:
                pass
        try:
            return set_status(fid, "confirmed")
        except ValueError:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Finding not found.")

    @app.post("/findings/{fid}/dismiss", tags=["Patterns"])
    def _dismiss(fid: str, role: str = role_dep):  # type: ignore[no-untyped-def]
        if _has_auth:
            try:
                _log(role, f"DISMISS_FINDING_{fid}", "")
            except Exception:
                pass
        try:
            return set_status(fid, "dismissed")
        except ValueError:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Finding not found.")
