"""Demo fixtures for Operation Redline (CAS-2026-102) — now DB-backed.

[`MOCK_ENTITIES`](seed_data.py:14) / [`MOCK_EDGES`](seed_data.py:49) are kept
as importable fallbacks, but [`ensure_seed_data()`](seed_data.py:73) writes
them into SQLite (via [`database.py`](database.py:1) + [`graph_store.py`](graph_store.py:1))
on startup so [`main.py`](main.py:1) serves persisted rows, not memory.
"""

from __future__ import annotations

from datetime import datetime, timezone

from database import get_db, init_db
from graph_store import upsert_edge, upsert_entity
from models import EntityNode, EvidenceEdge

DEFAULT_CASE_ID = "CAS-2026-102"

# Production: users come ONLY from env (no hardcoded passwords).
# Format: CYSLOP_SEED_USERS="BADGE:password:role:CASE, ..." e.g.
#   "OFFICER-4402:s3cr3t:lead_investigator:CAS-2026-102,ANALYST-101:s3cr3t:analyst:CAS-2026-102"
# Demo convenience: ALLOW_INSECURE_DEV=1 seeds OFFICER-4402/ANALYST-101 with
# CYSLOP_DEMO_PASSWORD (default demo-only) when CYSLOP_SEED_USERS is unset.
def _users_from_env() -> list[tuple[str, str, str, str]]:
    import os
    raw = os.environ.get("CYSLOP_SEED_USERS", "").strip()
    users: list[tuple[str, str, str, str]] = []
    if raw:
        for chunk in raw.split(","):
            parts = [p.strip() for p in chunk.split(":")]
            if len(parts) != 4 or not all(parts):
                raise RuntimeError(
                    f"Bad CYSLOP_SEED_USERS entry {chunk!r}; want BADGE:password:role:CASE")
            badge, pwd, role, case = parts
            if role not in ("lead_investigator", "analyst"):
                raise RuntimeError(f"Bad role {role!r} for {badge}")
            if len(pwd) < 8:
                raise RuntimeError(f"Seed password for {badge} must be >= 8 chars")
            users.append((badge, pwd, role, case))
        return users
    if os.environ.get("ALLOW_INSECURE_DEV", "0") == "1":
        demo_pwd = os.environ.get("CYSLOP_DEMO_PASSWORD", "demo-only-change-me")
        return [
            ("OFFICER-4402", demo_pwd, "lead_investigator", DEFAULT_CASE_ID),
            ("ANALYST-101", demo_pwd, "analyst", DEFAULT_CASE_ID),
        ]
    return []


def ensure_seed_users() -> bool:
    """Insert env-provided users with hashed passwords if missing."""
    from datetime import datetime, timezone
    from security import hash_password
    init_db()
    users = _users_from_env()
    if not users:
        return False
    seeded = False
    with get_db() as conn:
        for badge_id, password, role, active_case in users:
            row = conn.execute(
                "SELECT badge_id FROM users WHERE badge_id = ?", (badge_id,)).fetchone()
            if row:
                continue
            conn.execute(
                """INSERT INTO users (badge_id, password_hash, role, active_case, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (badge_id, hash_password(password), role, active_case,
                 datetime.now(timezone.utc).isoformat()))
            seeded = True
    return seeded

MOCK_ENTITIES = {
    "ENT-001": EntityNode(id="ENT-001", name="Ramesh Kumar", aliases=["Ramash"],
                          phone_numbers=["+91-9876543210", "+91-9123000001"],
                          entity_type="PERSON", base_risk_score=65.0),
    "ENT-002": EntityNode(id="ENT-002", name="Suresh Sharma", aliases=["Sureth"],
                          phone_numbers=["+91-9123456780", "+91-9120202020"],
                          entity_type="PERSON", base_risk_score=75.0),
    "ENT-003": EntityNode(id="ENT-003", name="Acc: 99884411", aliases=["Hawala Drop"],
                          phone_numbers=[], entity_type="BANK_ACCOUNT", base_risk_score=50.0),
    "ENT-004": EntityNode(id="ENT-004", name="DL-01-AB-4402", aliases=["Getaway Sedan"],
                          phone_numbers=[], entity_type="VEHICLE", base_risk_score=30.0),
}

MOCK_EDGES = [
    EvidenceEdge(source_id="ENT-001", target_id="ENT-002", relation_type="FREQUENT_CALLS",
                 confidence_score=0.92,
                 evidence_source="CDR Analytics: 43 late night calls over 3 days"),
    EvidenceEdge(source_id="ENT-002", target_id="ENT-003", relation_type="SUSPICIOUS_TRANSFER",
                 confidence_score=0.88,
                 evidence_source="Financial Intelligence Unit: Layered transaction spike"),
    EvidenceEdge(source_id="ENT-002", target_id="ENT-004", relation_type="OWNS_VEHICLE",
                 confidence_score=0.95, evidence_source="State Transport RTO Database"),
]

MOCK_LINK_IDS = ["LINK-001", "LINK-002", "LINK-003"]


def ensure_seed_data(case_id: str = DEFAULT_CASE_ID) -> bool:
    """Create case + seed rows if empty. Returns True when seeded."""
    init_db()
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO cases (id, title, description, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (case_id, "Operation Redline",
             "Demo network: 3 core suspects linked via shared burner + money trail.",
             "OPEN", datetime.now(timezone.utc).isoformat()))
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM entities WHERE case_id = ?", (case_id,)).fetchone()["c"]
    if count > 0:
        return False
    for entity in MOCK_ENTITIES.values():
        upsert_entity(entity, case_id)
    for link_id, edge in zip(MOCK_LINK_IDS, MOCK_EDGES):
        upsert_edge(edge, case_id, link_id=link_id)
        with get_db() as conn:
            conn.execute(
                """INSERT INTO evidence_sources (edge_id, source_type, reference, details)
                   VALUES (?, ?, ?, ?)""",
                (link_id, "SYSTEM", edge.evidence_source, edge.evidence_source))
    return True
