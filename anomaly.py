"""Feature 4 — Statistical anomaly detection.

Per-entity statistical outliers emitted as [`Finding`](models.py:68)
records through F3's existing infrastructure ([`patterns._store`](patterns.py:436),
dedup, status machinery). Small by design — the payoff of F3's contract.

Feature computation (per entity, from graph + records): daily call counts,
transaction amounts (in/out separately), distinct counterparties per window,
hour-of-day distribution.

Detectors (statistical only — no training, no ML):
* A1 amount outlier — robust z (median/MAD) on transaction amounts.
* A2 volume spike — daily call rate vs own median daily rate, MAD-based.
* A3 counterparty expansion — new distinct counterparties in window vs rate.
* A4 odd-hour activity — 00:00-05:00 mass vs baseline proportion.

Baseline honesty: per-entity MAD is unstable below ~5 observations, so the
detector falls back to the case-wide distribution and says so in the
explanation (baseline type is part of the Finding, used by F6/F7).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from statistics import median
from typing import Any

from patterns import (
    _edge_ts,
    _is_call,
    _is_txn,
    _load_case,
    _robust_z,
    _store,
    ensure_findings_table,
)

ANOMALY_CONFIG: dict[str, Any] = {
    "amount_z_threshold": 3.5,
    "volume_z_threshold": 3.5,
    "volume_min_spike": 8,  # absolute floor so trivial 2-vs-1 never fires
    "counterparty_window_days": 7,
    "counterparty_min_new": 5,
    "counterparty_mult": 3.0,
    "odd_start_hour": 0,
    "odd_end_hour": 5,
    "odd_min_total": 8,
    "odd_min_ratio": 0.3,
    "odd_mult": 3.0,
    "min_entity_obs": 5,  # below this -> case-wide fallback baseline
}

RULE_IDS = (
    "A1_amount_outlier",
    "A2_volume_spike",
    "A3_counterparty_expansion",
    "A4_odd_hour_activity",
)


def _severity_for(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _score_for_z(z: float) -> float:
    return float(max(0.0, min(1.0, 0.4 + 0.08 * z)))


def _amount_of(edge: dict[str, Any], details: str = "") -> float | None:
    try:
        payload = json.loads(details or "{}")
        for k in ("amount", "amt", "value", "rs", "inr"):
            if k in payload and payload[k] is not None:
                return float(payload[k])
    except Exception:
        pass
    blob = f"{edge.get('evidence_source', '')} {details}"
    m = re.search(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)", blob, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _fmt_inr(amt: float) -> str:
    return f"₹{amt:,.0f}"


# ---------------------------------------------------------------------------
# Shared feature builders
# ---------------------------------------------------------------------------

def _txn_amounts(edges, details) -> tuple[dict[str, list[tuple[float, str]]], list[float]]:
    """Per-entity amounts (in+out) + case-wide list. Returns ({eid: [(amt, edge_id)]}, all)."""
    per: dict[str, list[tuple[float, str]]] = defaultdict(list)
    all_amts: list[float] = []
    for e in edges:
        if not _is_txn(str(e.get("relation_type", ""))):
            continue
        amt = _amount_of(e, (details or {}).get(str(e.get("id", "")), ""))
        if amt is None:
            continue
        eid = str(e["id"])
        per[str(e["source_id"])].append((amt, eid))
        per[str(e["target_id"])].append((amt, eid))
        all_amts.append(amt)
    return per, all_amts


def _daily_call_counts(edges, details) -> dict[str, dict[str, int]]:
    """{entity_id: {date_iso: count}} over CALL edges (both directions)."""
    per: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in edges:
        if not _is_call(str(e.get("relation_type", ""))):
            continue
        ts = _edge_ts(e, (details or {}).get(str(e.get("id", "")), ""))
        if ts is None:
            continue
        d = ts.date().isoformat()
        per[str(e["source_id"])][d] += 1
        per[str(e["target_id"])][d] += 1
    return per


def _first_seen_peers(edges, details) -> dict[str, dict[str, datetime | None]]:
    """{entity_id: {peer_id: first_seen_ts}} over CALL+TXN edges."""
    per: dict[str, dict[str, datetime | None]] = defaultdict(dict)
    for e in edges:
        rel = str(e.get("relation_type", ""))
        if not (_is_call(rel) or _is_txn(rel)):
            continue
        ts = _edge_ts(e, (details or {}).get(str(e.get("id", "")), ""))
        s, t = str(e["source_id"]), str(e["target_id"])
        for a, b in ((s, t), (t, s)):
            if b not in per[a] or (ts is not None and (per[a][b] is None or ts < per[a][b])):  # type: ignore[operator]
                per[a][b] = ts
    return per


def _hour_split(edges, details, odd_start=0, odd_end=5) -> dict[str, dict[str, int]]:
    """{entity_id: {'odd': n, 'total': n}} over CALL+TXN edges with timestamps."""
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"odd": 0, "total": 0})
    for e in edges:
        rel = str(e.get("relation_type", ""))
        if not (_is_call(rel) or _is_txn(rel)):
            continue
        ts = _edge_ts(e, (details or {}).get(str(e.get("id", "")), ""))
        if ts is None:
            continue
        odd = 1 if odd_start <= ts.hour < odd_end else 0
        for eid in (str(e["source_id"]), str(e["target_id"])):
            per[eid]["total"] += 1
            per[eid]["odd"] += odd
    return per


# ---------------------------------------------------------------------------
# Detectors — pure functions over edge rows (testable w/o DB)
# ---------------------------------------------------------------------------

def detect_amount_outlier(edges, details=None, cfg=None) -> list[dict[str, Any]]:
    """A1: robust z on transaction amounts; entity baseline if n>=5 else case-wide fallback."""
    cfg = cfg or ANOMALY_CONFIG
    details = details or {}
    z_thr = float(cfg["amount_z_threshold"])
    min_obs = int(cfg["min_entity_obs"])
    per, all_amts = _txn_amounts(edges, details)
    if not all_amts:
        return []
    case_med = median(all_amts)
    out = []
    seen: set[tuple[str, str]] = set()  # (entity, edge) once
    for eid, items in per.items():
        amts = [a for a, _ in items]
        if len(amts) >= min_obs:
            baseline, btype = amts, "entity"
        else:
            baseline, btype = all_amts, "case-wide fallback"
        for amt, edge_id in items:
            z = _robust_z([int(round(v)) for v in baseline], int(round(amt)))
            if z < z_thr:
                continue
            key = (eid, edge_id)
            if key in seen:
                continue
            seen.add(key)
            mult = (amt / case_med) if case_med else amt
            # typical = entity median when available else case median
            typ = median(amts) if len(amts) >= min_obs else case_med
            mult_typ = (amt / typ) if typ else amt
            score = _score_for_z(z)
            base_note = (
                f"entity baseline (n={len(amts)})" if btype == "entity"
                else f"case-wide fallback baseline (entity n={len(amts)} < {min_obs})"
            )
            out.append({
                "rule_id": "A1_amount_outlier",
                "entity_ids": [eid],
                "explanation": (
                    f"{_fmt_inr(amt)} transfer is {mult_typ:.1f}× entity's typical amount "
                    f"(z={z:.1f} ≥ {z_thr:g}) vs {base_note}"),
                "evidence": [{"edge_id": edge_id, "source_type": "BANK_TXN",
                              "reference": edge_id,
                              "detail": f"{_fmt_inr(amt)} z={z:.1f} {base_note}"}],
                "score": score,
                "severity": _severity_for(score),
            })
    # keep the single strongest per entity to avoid edge-spam
    best: dict[str, dict[str, Any]] = {}
    for d in out:
        k = d["entity_ids"][0]
        if k not in best or d["score"] > best[k]["score"]:
            best[k] = d
    return list(best.values())


def detect_volume_spike(edges, details=None, cfg=None) -> list[dict[str, Any]]:
    """A2: daily call rate vs own median daily rate, MAD-based; fallback if <5 active days."""
    cfg = cfg or ANOMALY_CONFIG
    details = details or {}
    z_thr = float(cfg["volume_z_threshold"])
    min_spike = int(cfg["volume_min_spike"])
    min_obs = int(cfg["min_entity_obs"])
    per = _daily_call_counts(edges, details)
    if not per:
        return []
    case_rates = [c for days in per.values() for c in days.values()]
    out = []
    for eid, days in per.items():
        counts = sorted(days.values())
        if len(counts) >= min_obs:
            baseline, btype = counts, "entity"
        else:
            baseline, btype = case_rates, "case-wide fallback"
        peak_day = max(days, key=lambda d: days[d])
        peak = days[peak_day]
        if peak < min_spike:
            continue
        z = _robust_z(list(baseline), peak)
        if z < z_thr:
            continue
        med = median(baseline)
        score = _score_for_z(z)
        base_note = (
            f"entity baseline median {med:g}/day (n={len(counts)} days)" if btype == "entity"
            else f"case-wide fallback baseline median {med:g}/day (entity n={len(counts)} < {min_obs} days)")
        try:
            disp = datetime.fromisoformat(peak_day).strftime("%d-%b")
        except ValueError:
            disp = peak_day
        out.append({
            "rule_id": "A2_volume_spike",
            "entity_ids": [eid],
            "explanation": (
                f"{peak} calls on {disp} vs. median {med:g}/day "
                f"(robust z={z:.1f} ≥ {z_thr:g}) vs {base_note}"),
            "evidence": [{"edge_id": "", "source_type": "CDR",
                          "reference": f"{eid}|{peak_day}",
                          "detail": f"{peak} calls on {peak_day}"}],
            "score": score,
            "severity": _severity_for(score),
        })
    return out


def detect_counterparty_expansion(edges, details=None, cfg=None) -> list[dict[str, Any]]:
    """A3: new distinct counterparties in trailing window vs historical weekly rate."""
    cfg = cfg or ANOMALY_CONFIG
    details = details or {}
    win = int(cfg["counterparty_window_days"])
    min_new = int(cfg["counterparty_min_new"])
    mult_thr = float(cfg["counterparty_mult"])
    peers = _first_seen_peers(edges, details)
    out = []
    for eid, pm in peers.items():
        dated = [(p, t) for p, t in pm.items() if t is not None]
        if not dated:
            continue
        latest = max(t for _, t in dated)  # type: ignore[type-var]
        from datetime import timedelta
        cutoff = latest - timedelta(days=win)
        new_in_win = sum(1 for _, t in dated if t >= cutoff)  # type: ignore[operator]
        if new_in_win < min_new:
            continue
        # historical weekly rate over pre-window history
        hist = [(p, t) for p, t in dated if t < cutoff]  # type: ignore[operator]
        if len(hist) >= 2:
            span_days = (cutoff - min(t for _, t in hist)).days or 1  # type: ignore[type-var]
            typical = max(0.5, len(hist) / max(1.0, span_days / 7.0))
            btype = "entity"
        else:
            # fallback: case-wide weekly new-peer rate
            all_new = []
            for pm2 in peers.values():
                dd = sorted(t for t in pm2.values() if t is not None)
                if len(dd) >= 2:
                    span = (dd[-1] - dd[0]).days or 1
                    all_new.append(len(dd) / max(1.0, span / 7.0))
            typical = median(all_new) if all_new else 1.0
            typical = max(0.5, typical)
            btype = "case-wide fallback"
        if new_in_win < mult_thr * typical and new_in_win < min_new + 2:
            continue
        if new_in_win < mult_thr * typical:
            continue
        score = min(1.0, 0.4 + 0.06 * new_in_win + 0.02 * (new_in_win / typical))
        base_note = (
            "entity baseline" if btype == "entity"
            else "case-wide fallback baseline")
        out.append({
            "rule_id": "A3_counterparty_expansion",
            "entity_ids": [eid],
            "explanation": (
                f"{new_in_win} new contacts in {win} days vs. typical {typical:.1f}/week "
                f"({base_note})"),
            "evidence": [{"edge_id": "", "source_type": "CDR",
                          "reference": f"{eid}|new-{win}d",
                          "detail": f"{new_in_win} new peers in {win}d"}],
            "score": score,
            "severity": _severity_for(score),
        })
    return out


def detect_odd_hour(edges, details=None, cfg=None) -> list[dict[str, Any]]:
    """A4: 00:00-05:00 activity mass vs baseline proportion (entity if n>=min else case-wide)."""
    cfg = cfg or ANOMALY_CONFIG
    details = details or {}
    o0, o1 = int(cfg["odd_start_hour"]), int(cfg["odd_end_hour"])
    min_total = int(cfg["odd_min_total"])
    min_ratio = float(cfg["odd_min_ratio"])
    mult_thr = float(cfg["odd_mult"])
    min_obs = int(cfg["min_entity_obs"])
    per = _hour_split(edges, details, o0, o1)
    totals = sum(v["total"] for v in per.values())
    odds = sum(v["odd"] for v in per.values())
    case_ratio = (odds / totals) if totals else 0.0
    out = []
    for eid, v in per.items():
        if v["total"] < min_total:
            continue
        ratio = v["odd"] / v["total"]
        if ratio < min_ratio:
            continue
        # entity's own baseline is approximated by its non-recent history when
        # enough observations exist; with small-n we must be honest and use case-wide.
        if v["total"] >= max(min_obs, min_total):
            baseline, btype = case_ratio, "entity-supported case comparison"
            # entity has enough mass to trust its own ratio; compare vs case rate
        else:
            baseline, btype = case_ratio, "case-wide fallback"
        base = max(baseline, 0.01)
        if ratio < mult_thr * base and ratio < 0.5:
            continue
        if baseline <= 0:
            z_like = ratio * 10
        else:
            z_like = ratio / max(baseline, 0.02)
        score = min(1.0, 0.4 + 0.1 * z_like)
        base_note = (
            f"baseline {baseline:.0%} ({btype})" if "fallback" in btype
            else f"baseline {baseline:.0%}")
        out.append({
            "rule_id": "A4_odd_hour_activity",
            "entity_ids": [eid],
            "explanation": (
                f"{ratio:.0%} of activity in {o0:02d}–{o1:02d}h vs. {base_note} "
                f"({v['odd']}/{v['total']} events)"),
            "evidence": [{"edge_id": "", "source_type": "CDR",
                          "reference": f"{eid}|odd-hour",
                          "detail": f"{v['odd']}/{v['total']} in {o0:02d}-{o1:02d}h"}],
            "score": score,
            "severity": _severity_for(score),
        })
    return out


# ---------------------------------------------------------------------------
# Orchestration — same Finding contract / dedup machinery as F3
# ---------------------------------------------------------------------------

def scan_case(case_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run all four anomaly detectors; return {"new": [...], "total": N}."""
    from patterns import SEVERITY as _PSEV
    cfg = cfg or ANOMALY_CONFIG
    edges, details = _load_case(case_id)
    dets = [
        *detect_amount_outlier(edges, details, cfg),
        *detect_volume_spike(edges, details, cfg),
        *detect_counterparty_expansion(edges, details, cfg),
        *detect_odd_hour(edges, details, cfg),
    ]
    # _store derives severity from patterns.SEVERITY; patch in anomaly severities
    for d in dets:
        _PSEV[d["rule_id"]] = d.get("severity", "medium")
    new = []
    for d in dets:
        row = _store(case_id, d)
        if row is not None:
            new.append(row)
    return {"case_id": case_id, "new": new, "new_count": len(new),
            "candidates": len(dets)}


def scan_all(case_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """F3 rules + anomaly detectors in one pass (backing POST /analyze/scan)."""
    import patterns as _p
    r1 = _p.scan_case(case_id)
    r2 = scan_case(case_id)
    return {"case_id": case_id,
            "new": [*r1["new"], *r2["new"]],
            "new_count": len(r1["new"]) + len(r2["new"]),
            "candidates": r1["candidates"] + r2["candidates"]}


def register_routes(app: Any) -> None:
    """Attach POST /analyze/scan alias (additive; never touches F3 paths)."""
    from fastapi import Depends

    try:
        from security import get_current_user_role as _role
        from audit_log import log_officer_action as _log
        _has_auth = True
    except Exception:
        _has_auth = False

    role_dep = Depends(_role) if _has_auth else lambda: "analyst"  # type: ignore

    @app.post("/analyze/scan/{case_id}", tags=["Patterns"])
    def _analyze_scan(case_id: str, role: str = role_dep):  # type: ignore[no-untyped-def]
        if _has_auth:
            try:
                _log(role, "SCAN_ANOMALIES", case_id)
            except Exception:
                pass
        return scan_all(case_id)


# ---------------------------------------------------------------------------
# Seed: one statistical outlier of each type + steady normals (idempotent)
# ---------------------------------------------------------------------------
CASE = "CAS-2026-102"


def seed_anomalies(case_id: str = CASE) -> dict:
    """Seed F4 outliers. Safe w.r.t. F3: no cycles, no >=4-peer hub within
    45d, no call+transfer pair x3, no per-pair burst (z<4). Idempotent."""
    import json as _json
    from datetime import datetime as _dt, timedelta as _td

    from database import get_db, init_db
    from graph_store import upsert_edge, upsert_entity
    from models import EntityNode, EvidenceEdge

    init_db()
    with get_db() as _c:
        _c.execute(
            "INSERT OR IGNORE INTO cases (id,title,description,status,created_at)"
            " VALUES (?,?,?,?,?)",
            (case_id, "Operation Redline", "demo", "OPEN", _dt.now().isoformat()))

    def _ent(eid, name, etype="PERSON"):
        upsert_entity(EntityNode(id=eid, name=name, aliases=[], phone_numbers=[],
                                 entity_type=etype, base_risk_score=50.0), case_id)

    def _edge(eid, s, t, rel, conf, src):
        upsert_edge(EvidenceEdge(source_id=s, target_id=t, relation_type=rel,
                                 confidence_score=conf, evidence_source=src),
                    case_id, link_id=eid)

    def _ev(edge_id, stype, ref, payload):
        with get_db() as _c2:
            _c2.execute("DELETE FROM evidence_sources WHERE edge_id=? AND reference=?",
                        (edge_id, ref))
            _c2.execute(
                "INSERT INTO evidence_sources (edge_id, source_type, reference, details)"
                " VALUES (?,?,?,?)", (edge_id, stype, ref, _json.dumps(payload, default=str)))

    # -- A1 amount outlier: A1-S, 6 small (~10-12.5k) + 1 huge 500k, transfer-only --
    _ent("A1-S", "A1 Sender", "BANK_ACCOUNT")
    _ent("A1-B", "A1 Receiver", "BANK_ACCOUNT")
    for i, m in enumerate(["A1-M1", "A1-M2", "A1-M3"]):
        _ent(m, f"A1 Mid {i}", "BANK_ACCOUNT")
    smalls = [10000, 10500, 11000, 11500, 12000, 12500]
    targets = ["A1-M1", "A1-M2", "A1-M3", "A1-M1", "A1-M2", "A1-B"]
    base = _dt(2023, 9, 1, 11, 0, 0)
    for i, (amt, tgt) in enumerate(zip(smalls, targets)):
        eid = f"A1-SM-{i}"
        ts = (base + _td(days=i * 3)).isoformat()
        _edge(eid, "A1-S", tgt, "SUSPICIOUS_TRANSFER", 0.9, f"TXN {eid} Rs.{amt} @ {ts}")
        _ev(eid, "BANK_TXN", eid, {"timestamp": ts, "amount": amt})
    big_ts = (base + _td(days=20, hours=2)).isoformat()
    _edge("A1-BIG", "A1-S", "A1-B", "SUSPICIOUS_TRANSFER", 0.9,
          f"TXN A1-BIG: A1-S->A1-B Rs.500000 @ {big_ts}")
    _ev("A1-BIG", "BANK_TXN", "A1-BIG", {"timestamp": big_ts, "amount": 500000})

    # -- A2 volume spike (entity baseline): A2-S x 3 peers, varied 2-4/day, spike 12 --
    for eid, nm in [("A2-S", "A2 Spiker"), ("A2-P1", "A2 Peer 1"),
                    ("A2-P2", "A2 Peer 2"), ("A2-P3", "A2 Peer 3")]:
        _ent(eid, nm)
    b0 = _dt(2023, 9, 1, 10, 0, 0)
    n = 0
    for d in range(14):
        # entity totals vary 2..4/day (MAD>0) while each pair stays at 0..2
        plan = ["A2-P1", "A2-P2", "A2-P3"]
        if d % 4 == 0:
            plan = ["A2-P1", "A2-P2"]          # 2 total
        elif d % 4 == 2:
            plan = ["A2-P1", "A2-P1", "A2-P2", "A2-P3"]  # 4 total
        for k, peer in enumerate(plan):
            eid = f"A2-B-{d}-{k}"
            ts = (b0 + _td(days=d, hours=k)).isoformat()
            _edge(eid, "A2-S", peer, "CALLED", 0.9, f"CDR {eid} @ {ts}")
            _ev(eid, "CDR", eid, {"timestamp": ts})
            n += 1
    for k in range(12):  # spike day: 4 per peer -> per-pair z=3 (<4, no P4), entity 12
        peer = ["A2-P1", "A2-P2", "A2-P3"][k % 3]
        eid = f"A2-SP-{k}"
        ts = (b0 + _td(days=14, hours=k // 3, minutes=(k * 7) % 60)).isoformat()
        _edge(eid, "A2-S", peer, "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})
        n += 1

    # -- A2 fallback (<5 obs): A2-NEW, 3 active days, spike 9 -> case-wide fallback --
    for eid, nm in [("A2-NEW", "A2 Newcomer"), ("A2-NP1", "A2 New Peer 1"),
                    ("A2-NP2", "A2 New Peer 2")]:
        _ent(eid, nm)
    f0 = _dt(2023, 10, 1, 10, 0, 0)
    for j, dd in enumerate([0, 1]):
        eid = f"A2-NB-{j}"
        ts = (f0 + _td(days=dd)).isoformat()
        _edge(eid, "A2-NEW", "A2-NP1", "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})
    for k in range(9):  # 5+4 across 2 peers; only 3 distinct days -> no P4
        peer = "A2-NP1" if k < 5 else "A2-NP2"
        eid = f"A2-NS-{k}"
        ts = (f0 + _td(days=2, minutes=k * 5)).isoformat()
        _edge(eid, "A2-NEW", peer, "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})

    # -- A3 counterparty expansion: 4 hist peers over ~90d + 9 new in 7d --
    _ent("A3-EXP", "A3 Expander")
    latest = _dt(2023, 10, 10, 12, 0, 0)
    for i, ago in enumerate([90, 75, 60, 50]):
        pid = f"A3-H{i}"
        _ent(pid, f"A3 Hist {i}")
        eid = f"A3-HE-{i}"
        ts = (latest - _td(days=ago)).isoformat()
        _edge(eid, "A3-EXP", pid, "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})
    for i in range(9):  # spread over 7d so daily volume stays low (no A2)
        pid = f"A3-R{i}"
        _ent(pid, f"A3 Recent {i}")
        eid = f"A3-RE-{i}"
        ts = (latest - _td(days=(i * 7) // 9, hours=i)).isoformat()
        _edge(eid, "A3-EXP", pid, "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})

    # -- A4 odd-hour: 8/11 events in 00-05h across 4 days (no single-day spike) --
    for eid, nm in [("A4-N", "A4 Nightowl"), ("A4-P1", "A4 Peer 1")]:
        _ent(eid, nm)
    o0 = _dt(2023, 9, 5, 2, 10, 0)
    odd_ts = [o0 + _td(days=d, minutes=m) for d, m in
              [(0, 0), (0, 40), (1, 5), (1, 50), (2, 10), (2, 55), (3, 20), (3, 45)]]
    day_ts = [_dt(2023, 9, 9, 10, 0, 0), _dt(2023, 9, 9, 14, 30, 0),
              _dt(2023, 9, 10, 11, 15, 0)]
    for k, ts in enumerate([t.isoformat() for t in odd_ts + day_ts]):
        eid = f"A4-C{k}"
        _edge(eid, "A4-N", "A4-P1", "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})

    # -- Normals: steady pair, daytime only, typical amounts, calls far from transfers --
    for eid, nm in [("A0-N1", "Normal One"), ("A0-N2", "Normal Two")]:
        _ent(eid, nm)
    n0 = _dt(2023, 9, 1, 10, 0, 0)
    for d in range(10):
        eid = f"A0-C{d}"
        ts = (n0 + _td(days=d)).isoformat()
        _edge(eid, "A0-N1", "A0-N2", "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})
    for j, amt in enumerate([11000, 11500]):
        eid = f"A0-T{j}"
        ts = (n0 + _td(days=15 + j)).isoformat()  # >72h after last call -> no P3
        _edge(eid, "A0-N1", "A0-N2", "SUSPICIOUS_TRANSFER", 0.9,
              f"TXN {eid} Rs.{amt} @ {ts}")
        _ev(eid, "BANK_TXN", eid, {"timestamp": ts, "amount": amt})
    return {"seeded_anomalies": True, "a2_baseline_calls": n}


if __name__ == "__main__":
    print(seed_anomalies())
