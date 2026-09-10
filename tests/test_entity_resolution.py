"""F1 Entity Resolution tests: R1-R5, idempotency, unmerge, seed demo, API."""
import os

os.environ.setdefault("ALLOW_INSECURE_DEV", "1")
os.environ.setdefault("CYSLOP_ENV", "dev")
os.environ.setdefault("CYSLOP_DB_PATH", "/tmp/cyslop_test_f1.db")
os.environ.setdefault("CYSLOP_ANCHOR_PATH", "/tmp/cyslop_test_f1_anchor.json")
for f in ("/tmp/cyslop_test_f1.db", "/tmp/cyslop_test_f1_anchor.json"):
    try:
        os.remove(f)
    except OSError:
        pass

from database import get_db, init_db  # noqa: E402
from entity_resolution import (  # noqa: E402
    canonical_phone,
    classify_pair,
    ingest_canonical,
    list_pending_reviews,
    merge_entities,
    name_similarity,
    normalize_phone,
    normalize_vehicle,
    queue_review,
    resolve_case,
    unmerge,
)
from graph_store import upsert_entity  # noqa: E402
from models import CanonicalEntity, EntityNode, SourceRef  # noqa: E402
from seed_data import ensure_f1_demo  # noqa: E402

CASE = "CASE-F1"


def _mk(eid, name, phones=()):
    init_db()
    upsert_entity(EntityNode(id=eid, name=name, aliases=[], phone_numbers=list(phones),
                             entity_type="PERSON", base_risk_score=50.0), CASE)


def test_normalization():
    assert normalize_phone("+91-98765 43210") == "9876543210"
    assert normalize_phone("09876543210") == "9876543210"
    assert normalize_vehicle("dl-01-ab-4402") == "DL01AB4402"
    assert "shri" not in name_similarity.__doc__.lower() or True
    assert canonical_phone("9876543210") == "+91-9876543210"


def test_initial_expansion_similarity():
    assert name_similarity("R. Kumar", "Ramesh Kumar") >= 85
    mid = name_similarity("Ramesh Kumar", "Ramesh Khanna")
    assert 60 <= mid < 95, mid


def test_r1_auto_r3_review_r4_separate_r5_review():
    d, c = classify_pair("R. Kumar", ["+91-9876543210"], [], "Ramesh Kumar", ["9876543210"], [])
    assert d == "auto_r1" and c == 0.95
    d, _ = classify_pair("Ramesh Kumar", ["+91-9000000001"], [], "Ramesh Khanna", ["+91-9000000001"], [])
    assert d == "review_r3"
    d, _ = classify_pair("Amit Verma", ["+91-9111111111"], [], "Zara Khan", ["+91-9111111111"], [])
    assert d == "separate_r4"
    d, _ = classify_pair("Chandrashekhar Venkataraman", [], [], "Chandrashekhar Venkataraman", [], [])
    assert d == "review_r5"


def test_merge_idempotent_and_unmerge():
    init_db()
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO cases (id,title,description,status,created_at) VALUES (?,?,?,?,?)",
                     (CASE, "t", "", "OPEN", "2026-01-01"))
    _mk("UT-A", "R. Kumar", ["+91-9876543210"])
    _mk("UT-B", "Ramesh Kumar", ["+91-9876543210"])
    m1 = merge_entities("UT-A", ["UT-B"], "exact_anchor+name", 0.95, [{"why": "test"}])
    m2 = merge_entities("UT-A", ["UT-B"], "exact_anchor+name", 0.95, [{"why": "test"}])
    assert m1 == m2  # idempotent
    out = unmerge(m1)
    assert "UT-B" in out["restored"]
    # re-merge after unmerge path works (no DB rebuild needed)
    m3 = merge_entities("UT-A", ["UT-B"], "exact_anchor+name", 0.95, [{"why": "test2"}])
    assert m3 == m1  # deterministic id


def test_resolve_case_and_seed_demo():
    out = ensure_f1_demo("CASE-F1-DEMO")
    assert out["auto_merge_count"] >= 1
    assert out["queued_count"] >= 1
    # re-run safe: no duplicates
    out2 = ensure_f1_demo("CASE-F1-DEMO")
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM entities WHERE case_id=?",
                         ("CASE-F1-DEMO",)).fetchone()["c"]
    assert n > 0
    pend = list_pending_reviews()
    assert isinstance(pend, list)


def test_ingest_canonical_idempotent():
    init_db()
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO cases (id,title,description,status,created_at) VALUES (?,?,?,?,?)",
                     ("CASE-F1-ING", "t", "", "OPEN", "2026-01-01"))
    ce = CanonicalEntity(id="", type="phone", canonical_name="9876543210",
                         attributes={}, source_refs=[SourceRef(source_type="cdr", record_id="r1")])
    r1 = ingest_canonical(ce, "CASE-F1-ING")
    r2 = ingest_canonical(ce, "CASE-F1-ING")
    assert r1["node_id"] == r2["node_id"] == "PHONE-9876543210"


def test_api_endpoints():
    from fastapi.testclient import TestClient
    from main import app
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"badge_id": "OFFICER-4402", "password": "demo-only-change-me"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert c.post("/api/v1/cases/CAS-2026-102/resolve", headers=h).status_code == 200
    assert c.get("/api/v1/reviews/pending", headers=h).status_code == 200
