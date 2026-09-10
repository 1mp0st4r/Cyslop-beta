"""Seed one crafted instance per F3 pattern (idempotent, fixed ids)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from database import get_db, init_db
from graph_store import upsert_edge, upsert_entity
from models import EntityNode, EvidenceEdge

CASE = "CAS-2026-102"


def _ev(edge_id: str, stype: str, ref: str, payload: dict) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM evidence_sources WHERE edge_id=? AND reference=?", (edge_id, ref))
        conn.execute(
            "INSERT INTO evidence_sources (edge_id, source_type, reference, details) VALUES (?,?,?,?)",
            (edge_id, stype, ref, json.dumps(payload, default=str)))


def _ent(eid: str, name: str, etype: str = "PERSON") -> None:
    upsert_entity(EntityNode(id=eid, name=name, aliases=[], phone_numbers=[],
                             entity_type=etype, base_risk_score=50.0), CASE)


def _edge(eid: str, s: str, t: str, rel: str, conf: float, src: str) -> None:
    upsert_edge(EvidenceEdge(source_id=s, target_id=t, relation_type=rel,
                             confidence_score=conf, evidence_source=src), CASE, link_id=eid)


def seed() -> dict:
    init_db()
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO cases (id,title,description,status,created_at) VALUES (?,?,?,?,?)",
                     (CASE, "Operation Redline", "demo", "OPEN", datetime.now().isoformat()))
    # P1 circular flow A->B->C->A within 30d
    for eid, nm in [("P1-A", "P1 Acct A"), ("P1-B", "P1 Acct B"), ("P1-C", "P1 Acct C")]:
        _ent(eid, nm, "BANK_ACCOUNT")
    p1 = [(("P1-A", "P1-B", "P1-T1", "2023-07-05T10:00:00", 250000),
           ("P1-B", "P1-C", "P1-T2", "2023-07-10T11:00:00", 245000),
           ("P1-C", "P1-A", "P1-T3", "2023-07-15T12:00:00", 248000))]
    for s, t, eid, ts, amt in p1[0]:
        _edge(eid, s, t, "SUSPICIOUS_TRANSFER", 0.9, f"TXN {eid}: {s}->{t} Rs.{amt} @ {ts}")
        _ev(eid, "BANK_TXN", eid, {"timestamp": ts, "amount": amt})
    # P2 burner hub: hub + 5 peers within ~20d
    _ent("P2-HUB", "+91-9111199999")
    base = datetime(2023, 6, 1, 10, 0, 0)
    for i in range(1, 6):
        pid = f"P2-P{i}"
        _ent(pid, f"Burner Contact {i}")
        eid = f"P2-C{i}"
        ts = (base + timedelta(days=i * 4)).isoformat()
        _edge(eid, "P2-HUB", pid, "CALLED", 0.92, f"CDR {eid}: P2-HUB -> {pid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts, "caller": "P2-HUB", "callee": pid})
    # P3 call-then-transfer x3 within 72h
    _ent("P3-A", "P3 Person A")
    _ent("P3-B", "P3 Person B")
    c0 = datetime(2023, 7, 1, 9, 0, 0)
    for i in range(3):
        ct = (c0 + timedelta(days=i * 5)).isoformat()
        tt = (c0 + timedelta(days=i * 5, hours=30)).isoformat()
        ce, te = f"P3-C{i}", f"P3-T{i}"
        _edge(ce, "P3-A", "P3-B", "CALLED", 0.92, f"CDR {ce} @ {ct}")
        _ev(ce, "CDR", ce, {"timestamp": ct})
        _edge(te, "P3-A", "P3-B", "SUSPICIOUS_TRANSFER", 0.88, f"TXN {te} @ {tt}")
        _ev(te, "BANK_TXN", te, {"timestamp": tt, "amount": 100000 + i})
    # P4 burst pair: 14d baseline 1/day + 8-call burst day
    _ent("P4-A", "P4 Person A")
    _ent("P4-B", "P4 Person B")
    b0 = datetime(2023, 8, 1, 10, 0, 0)
    n = 0
    for d in range(14):
        eid = f"P4-BASE-{d}"
        ts = (b0 + timedelta(days=d)).isoformat()
        _edge(eid, "P4-A", "P4-B", "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})
        n += 1
    for h in range(8):
        eid = f"P4-BURST-{h}"
        ts = (b0 + timedelta(days=14, hours=h)).isoformat()
        _edge(eid, "P4-A", "P4-B", "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})
        n += 1
    # Steady control pair: 1/day x 21, no burst
    _ent("P4-S1", "Steady One")
    _ent("P4-S2", "Steady Two")
    for d in range(21):
        eid = f"P4-ST-{d}"
        ts = (b0 + timedelta(days=d, hours=2)).isoformat()
        _edge(eid, "P4-S1", "P4-S2", "CALLED", 0.9, f"CDR {eid} @ {ts}")
        _ev(eid, "CDR", eid, {"timestamp": ts})
    return {"seeded": True, "p4_calls": n}


if __name__ == "__main__":
    print(seed())
