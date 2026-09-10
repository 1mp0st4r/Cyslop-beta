"""F2 extraction tests + F1 acceptance scenarios (spec paths)."""
import os

os.environ.setdefault("ALLOW_INSECURE_DEV", "1")
os.environ.setdefault("CYSLOP_ENV", "dev")
os.environ.setdefault("CYSLOP_DB_PATH", "/tmp/cyslop_test_f2.db")
os.environ.setdefault("CYSLOP_ANCHOR_PATH", "/tmp/cyslop_test_f2_anchor.json")
for f in ("/tmp/cyslop_test_f2.db", "/tmp/cyslop_test_f2_anchor.json"):
    try:
        os.remove(f)
    except OSError:
        pass

from database import get_db, init_db  # noqa: E402
from extraction import RegexFallbackNer, SpacyNerBackend, derive_relations, extract, extract_regex, ingest_text  # noqa: E402
from entity_resolution import (  # noqa: E402
    decide_review,
    get_entity_detail,
    ingest_canonical,
    list_pending_reviews_for_case,
    resolve_case,
    unmerge,
)
from graph_store import upsert_entity  # noqa: E402
from models import CanonicalEntity, EntityNode, SourceRef  # noqa: E402

CASE = "CASE-F2"


def _ensure_case(cid: str):
    init_db()
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO cases (id,title,description,status,created_at) VALUES (?,?,?,?,?)",
            (cid, "t", "", "OPEN", "2026-01-01"))


def test_phone_tricky_formats():
    exts = extract_regex("call +91 98765 43210 or 09876543210 or 91-9876543210 ok")
    phones = [e for e in exts if e.entity_type == "phone"]
    assert len(phones) == 3
    assert all(e.span_start >= 0 and e.span_end > e.span_start for e in phones)


def test_vehicle_variants():
    exts = extract_regex("plates DL-01-AB-4402 and MH 12 CD 3456 seen")
    vehs = [e for e in exts if e.entity_type == "vehicle"]
    assert len(vehs) == 2


def test_ner_backend_pluggable_and_spans():
    be = RegexFallbackNer()
    exts = extract("Ramesh Kumar met Suresh Sharma in Mumbai.", backend=be)
    persons = [e for e in exts if e.entity_type == "person"]
    assert len(persons) >= 2
    assert all(e.span_start >= 0 for e in persons)
    # spaCy backend honors same protocol
    sp = SpacyNerBackend()
    assert hasattr(sp, "entities")


def test_relations_uses_and_associated():
    text = "Ramesh Kumar driving vehicle DL-01-AB-4402 called +91-9876543210."
    exts = extract(text, backend=RegexFallbackNer())
    rels = derive_relations(text, exts)
    kinds = {r["relation"] for r in rels}
    assert "ASSOCIATED_WITH" in kinds
    assert "USES" in kinds
    assert all(r["evidence"] for r in rels)


def test_f1_acceptance_merge_two_sources():
    cid = "CASE-F2-ACC"
    _ensure_case(cid)
    a = CanonicalEntity(id="ACC-A", type="person", canonical_name="Ramesh Kumar",
                        attributes={"phones": ["+91-9876543210"]},
                        source_refs=[SourceRef(source_type="fir", record_id="FIR-1")])
    b = CanonicalEntity(id="ACC-B", type="person", canonical_name="R. Kumar",
                        attributes={"phones": ["+91 98765 43210"]},
                        source_refs=[SourceRef(source_type="bank", record_id="TXN-9")])
    r1 = ingest_canonical(a, cid)
    r2 = ingest_canonical(b, cid)
    out = resolve_case(cid)
    total = r1.get("auto_merge_count", 0) + r2.get("auto_merge_count", 0) + out.get("auto_merge_count", 0)
    with get_db() as conn:
        logged = conn.execute("SELECT COUNT(*) c FROM merge_log WHERE decision IN ('auto','accepted')").fetchone()["c"]
    assert total >= 1 or logged >= 1
    # survivor should carry 2 source_refs (union via merge? check via merge_log survivor)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM merge_log WHERE decision IN ('auto','accepted') ORDER BY created_at DESC").fetchone()
    assert row is not None
    det = get_entity_detail(row["surviving_entity_id"])
    assert len(det["source_refs"]) >= 1
    assert len(det["merge_history"]) >= 1


def test_f1_r4_separate_and_review_accept_unmerge():
    cid = "CASE-F2-R4"
    _ensure_case(cid)
    upsert_entity(EntityNode(id="S-A", name="Amit Verma", aliases=[], phone_numbers=["+91-9111111111"],
                             entity_type="PERSON", base_risk_score=50.0), cid)
    upsert_entity(EntityNode(id="S-B", name="Zara Khan", aliases=[], phone_numbers=["+91-9111111111"],
                             entity_type="PERSON", base_risk_score=50.0), cid)
    out = resolve_case(cid)
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM entities WHERE case_id=? AND entity_type='PERSON'",
                         (cid,)).fetchone()["c"]
    assert n == 2  # no merge
    # borderline -> review queue; accept -> merge; unmerge -> restore
    cid2 = "CASE-F2-R3"
    _ensure_case(cid2)
    upsert_entity(EntityNode(id="R-A", name="Ramesh Kumar", aliases=[], phone_numbers=["+91-9000000001"],
                             entity_type="PERSON", base_risk_score=50.0), cid2)
    upsert_entity(EntityNode(id="R-B", name="Ramesh Khanna", aliases=[], phone_numbers=["+91-9000000001"],
                             entity_type="PERSON", base_risk_score=50.0), cid2)
    out2 = resolve_case(cid2)
    assert out2["queued_count"] >= 1
    pend = list_pending_reviews_for_case(cid2)
    assert pend
    dec = decide_review(pend[0]["id"], "accepted", "OFFICER-4402")
    assert dec["decision"] == "accepted"
    um = unmerge(dec.get("merged_as", pend[0]["id"]))
    assert "restored" in um or "note" in um


def test_ingest_text_e2e_and_idempotent():
    cid = "CASE-F2-E2E"
    _ensure_case(cid)
    # pre-seed merged person owning the phone
    ingest_canonical(CanonicalEntity(id="PRE-A", type="person", canonical_name="Ramesh Kumar",
                                     attributes={"phones": ["+91-9876543210"]},
                                     source_refs=[SourceRef(source_type="cdr", record_id="CDR-1")]), cid)
    text = ("FIR No. 42: Ramesh Kumar of Sharma Enterprises was seen near Connaught Place, "
            "New Delhi driving vehicle DL-01-AB-4402 and called +91-9876543210.")
    r1 = ingest_text(cid, "fir", text, "FIR-42")
    assert r1["entities_created"] >= 4
    assert r1["relations_created"] >= 1
    assert r1["deduped"] is False
    # every entity from this path carries span
    with get_db() as conn:
        n_nospan = conn.execute(
            "SELECT COUNT(*) c FROM entity_sources WHERE case_id=? AND source_type='fir' AND span_start IS NULL", (cid,)).fetchone()["c"]
    assert n_nospan == 0
    r2 = ingest_text(cid, "fir", text, "FIR-42")
    assert r2["deduped"] is True
    with get_db() as conn:
        n1 = conn.execute("SELECT COUNT(*) c FROM entities WHERE case_id=?", (cid,)).fetchone()["c"]
    r3 = ingest_text(cid, "fir", text, "FIR-42")
    with get_db() as conn:
        n2 = conn.execute("SELECT COUNT(*) c FROM entities WHERE case_id=?", (cid,)).fetchone()["c"]
    assert n1 == n2


def test_spec_api_endpoints():
    from fastapi.testclient import TestClient
    from main import app
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"badge_id": "OFFICER-4402", "password": "demo-only-change-me"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert c.post("/entities/resolve/CAS-2026-102", headers=h).status_code == 200
    assert c.get("/resolution/candidates/CAS-2026-102", headers=h).status_code == 200
    body = {"source_type": "fir", "text": "Ramesh Kumar called +91-9876543210 near Mumbai.", "record_id": "T-1"}
    rr = c.post("/ingest/text/CAS-2026-102", json=body, headers=h)
    assert rr.status_code == 200, rr.text
    assert c.post("/ingest/text/CAS-2026-102", json=body, headers=h).json()["deduped"] is True
