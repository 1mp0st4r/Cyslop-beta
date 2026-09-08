"""Replaceable demo fixtures for Operation Redline (CAS-2026-102).

This module holds the in-memory mock graph previously embedded in
[`main.py`](main.py:1). Swap these dicts/lists with real DB/Neo4j queries
without touching the API layer — [`main.py`](main.py:1) imports
[`MOCK_ENTITIES`](seed_data.py:1) and [`MOCK_EDGES`](seed_data.py:1) from here.
For regenerating a larger synthetic dataset see
[`seed_synthetic_data.py`](scripts/seed_synthetic_data.py:1).
"""

from models import EntityNode, EvidenceEdge

# Mock in-memory database matching Operation Redline (CAS-2026-102)
MOCK_ENTITIES = {
    "ENT-001": EntityNode(
        id="ENT-001",
        name="Ramesh Kumar",
        aliases=["Ramash"],
        phone_numbers=["+91-9876543210", "+91-9123000001"],
        entity_type="PERSON",
        base_risk_score=65.0,
    ),
    "ENT-002": EntityNode(
        id="ENT-002",
        name="Suresh Sharma",
        aliases=["Sureth"],
        phone_numbers=["+91-9123456780", "+91-9120202020"],
        entity_type="PERSON",
        base_risk_score=75.0,
    ),
    "ENT-003": EntityNode(
        id="ENT-003",
        name="Acc: 99884411",
        aliases=["Hawala Drop"],
        phone_numbers=[],
        entity_type="BANK_ACCOUNT",
        base_risk_score=50.0,
    ),
    "ENT-004": EntityNode(
        id="ENT-004",
        name="DL-01-AB-4402",
        aliases=["Getaway Sedan"],
        phone_numbers=[],
        entity_type="VEHICLE",
        base_risk_score=30.0,
    ),
}

MOCK_EDGES = [
    EvidenceEdge(
        source_id="ENT-001",
        target_id="ENT-002",
        relation_type="FREQUENT_CALLS",
        confidence_score=0.92,
        evidence_source="CDR Analytics: 43 late night calls over 3 days",
    ),
    EvidenceEdge(
        source_id="ENT-002",
        target_id="ENT-003",
        relation_type="SUSPICIOUS_TRANSFER",
        confidence_score=0.88,
        evidence_source="Financial Intelligence Unit: Layered transaction spike",
    ),
    EvidenceEdge(
        source_id="ENT-002",
        target_id="ENT-004",
        relation_type="OWNS_VEHICLE",
        confidence_score=0.95,
        evidence_source="State Transport RTO Database",
    ),
]
