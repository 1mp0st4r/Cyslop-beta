"""F5 source adapter tests: registry, alias-driven merge, OBSERVED_AT/USES,
idempotency, and the full 7-source pipeline demo (>=5 sources in findings
inputs)."""
import csv
import io
import json
import os
from pathlib import Path

os.environ.setdefault("ALLOW_INSECURE_DEV", "1")
os.environ.setdefault("CYSLOP_ENV", "dev")
os.environ.setdefault("CYSLOP_DB_PATH", "/tmp/cyslop_test_f5.db")
os.environ.setdefault("CYSLOP_ANCHOR_PATH", "/tmp/cyslop_test_f5_anchor.json")
for f in ("/tmp/cyslop_test_f5.db", "/tmp/cyslop_test_f5_anchor.json"):
    try:
        os.remove(f)
    except OSError:
        pass

from database import get_db, init_db  # noqa: E402
from graph_store import get_edges, get_entities, upsert_entity  # noqa: E402
from ingestion.adapters import (  # noqa: E402
    dispatch_source, get_adapter, ingest_all_fixtures, list_source_types)
from ingestion.adapters.alias_resolution import alias_aware_resolve  # noqa: E402
from ingestion.adapters.base import get_edge_props  # noqa: E402
from ingestion.adapters.criminal_history import CriminalHistoryAdapter  # noqa: E402
from models import EntityNode  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
CSV_TEXT = (FIXTURES / "criminal_history.csv").read_text(encoding="utf-8")
SURV = json.loads((FIXTURES / "surveillance_reports.json").read_text(encoding="utf-8"))
SOCIAL = json.loads((FIXTURES / "social_media.json").read_text(encoding="utf-8"))
AGENCY = json.loads((FIXTURES / "agency_reports.json").read_text(encoding="utf-8"))


def _entities(case_id):
    return get_entities(case_id)


def _edges(case_id):
    _, raw = get_edges(case_id)
    return raw


def _ensure_case(case_id):
    from datetime import datetime, timezone

    init_db()
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO cases (id, title, description, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (case_id, "F5 test case", "", "OPEN",
             datetime.now(timezone.utc).isoformat()))


# ---------------------------------------------------------------- registry
def test_registry_has_four_new_sources():
    srcs = list_source_types()
    for st in ("criminal_history", "surveillance_report", "social_media",
               "agency_report"):
        assert st in srcs
    assert issubclass(get_adapter("criminal_history"), CriminalHistoryAdapter)


def test_criminal_history_parse_shape():
    recs = CriminalHistoryAdapter().parse(CSV_TEXT)
    assert len(recs) == 3
    r0 = recs[0]
    assert r0.name == "Vikram Rana"
    assert "Bunty" in r0.aliases and "Vikram Singh Rathore" in r0.aliases
    assert r0.phones == ["+91-9812345678"]
    assert any(rel["target"] == "FIR-2023-045" and
               rel["relation"] == "ASSOCIATED_WITH" for rel in r0.relations)


# ------------------------------------------------- alias-driven merge test
def test_alias_causes_merge_name_phone_alone_would_not():
    case = "CASE-F5-ALIAS"
    _ensure_case(case)
    # Entity known only as "Vikram S. Rathore" + phone (from an FIR-like source)
    upsert_entity(EntityNode(id="P-RATHORE", name="Vikram S. Rathore",
                             aliases=[], phone_numbers=["+91-9812345678"],
                             entity_type="PERSON", base_risk_score=50.0), case)
    # Criminal history row: different primary name, same phone, alias matches
    out = dispatch_source("criminal_history", CSV_TEXT, case)
    assert out["record_count"] == 3
    before = [e for e in _entities(case) if e.entity_type == "PERSON"]
    # name+phone alone: primary names "Vikram Rana" vs "Vikram S. Rathore"
    # score < 85 -> F1 resolve_case queues/keeps separate; the alias pass
    # (alias "Vikram Singh Rathore" vs name "Vikram S. Rathore") unlocks merge.
    assert all("Rathore" not in e.name or e.name == "Vikram S. Rathore"
               for e in before)
    alias_out = alias_aware_resolve(case)
    assert alias_out["alias_auto_merge_count"] >= 1
    persons_after = [e for e in _entities(case) if e.entity_type == "PERSON"]
    names = {e.name for e in persons_after}
    assert not any("Vikram Rana" == n for n in names)  # merged away
    survivor = [e for e in persons_after if "Rathore" in e.name]
    assert survivor and "Vikram Singh Rathore" in survivor[0].aliases
    # idempotent: second pass no-ops
    again = alias_aware_resolve(case)
    assert again["alias_auto_merge_count"] == 0


# ------------------------------------------------ surveillance OBSERVED_AT
def test_surveillance_report_creates_observed_at_and_uses():
    case = "CASE-F5-SURV"
    _ensure_case(case)
    out = dispatch_source("surveillance_report", SURV, case)
    rec0 = out["records"][0]
    assert rec0["observed"], "expected OBSERVED_AT edge for SURV-001"
    eid = rec0["observed"]["observed_at_edge"]
    edges = _edges(case)
    by_id = {e["id"]: e for e in edges}
    assert eid in by_id
    assert by_id[eid]["relation_type"] == "OBSERVED_AT"
    props = get_edge_props(eid)
    assert props.get("observed_at", "").startswith("2026-08-14T21:35:00")
    loc = rec0["observed"]["location_node"]
    loc_entity = [e for e in _entities(case) if e.id == loc]
    assert loc_entity and loc_entity[0].entity_type == "LOCATION"
    # USES edge: person -> known phone in same sentence (F2 derivation)
    uses = [e for e in edges if e["relation_type"] == "USES"]
    assert uses, "expected at least one USES edge from the surveillance text"


def test_surveillance_observed_at_edge_idempotent():
    case = "CASE-F5-SURV-IDEM"
    _ensure_case(case)
    dispatch_source("surveillance_report", SURV[:1], case)
    n1 = len(_edges(case))
    out2 = dispatch_source("surveillance_report", SURV[:1], case)
    assert out2["records"][0]["text_result"]["deduped"] is True
    n2 = len(_edges(case))
    assert n1 == n2, "re-ingesting the same report must not add edges"


# ------------------------------------------------------------ social media
def test_social_media_mentions_become_communicates_with():
    case = "CASE-F5-SOCIAL"
    _ensure_case(case)
    out = dispatch_source("social_media", SOCIAL, case)
    assert out["record_count"] == 3
    comm = [e for e in _edges(case) if e["relation_type"] == "COMMUNICATES_WITH"]
    # SM-001: 3 mentions, SM-002: 1, SM-003: 1 -> 5 edges
    assert len(comm) == 5
    evid = {e["evidence_source"] for e in comm}
    assert any("social_media" in ev for ev in evid)
    # idempotent
    dispatch_source("social_media", SOCIAL, case)
    assert len([e for e in _edges(case)
                if e["relation_type"] == "COMMUNICATES_WITH"]) == 5


# ----------------------------------------------------------- agency report
def test_agency_report_runs_f2_pipeline_and_is_idempotent():
    case = "CASE-F5-AGENCY"
    _ensure_case(case)
    out = dispatch_source("agency_report", AGENCY, case)
    assert out["record_count"] == 2
    assert out["records"][0]["text_result"]["entities_created"] > 0
    before = len(_entities(case))
    out2 = dispatch_source("agency_report", AGENCY, case)
    assert all(r["text_result"]["deduped"] for r in out2["records"])
    assert len(_entities(case)) == before


# --------------------------------------------------------- 7-source demo
def test_full_seven_source_demo_reflects_five_plus_sources():
    case = "CASE-F5-DEMO"
    summary = ingest_all_fixtures(case)
    srcs = summary["sources"]
    assert set(srcs) == {"fir_cdr_txn", "criminal_history", "surveillance_report",
                         "social_media", "agency_report"}
    # distinct relation types across the case == proxy for source coverage
    relations = {e["relation_type"] for e in _edges(case)}
    # FIR: CO_MENTIONED, CDR: CALLED, TXN: SUSPICIOUS_TRANSFER,
    # CH: ASSOCIATED_WITH, SURV: OBSERVED_AT (+USES), SM: COMMUNICATES_WITH,
    # AGY: TEXT ASSOCIATED_WITH/USES
    for expected in ("CO_MENTIONED", "CALLED", "SUSPICIOUS_TRANSFER",
                     "ASSOCIATED_WITH", "OBSERVED_AT", "COMMUNICATES_WITH"):
        assert expected in relations, f"missing {expected}; got {relations}"
    assert len(relations) >= 5
    # alias pass consolidates the demo case too
    alias_aware_resolve(case)
    persons = [e for e in _entities(case) if e.entity_type == "PERSON"]
    assert len(persons) > 0
    # entities carry evidence from multiple sources via source_refs/edges
    assert len(_edges(case)) > 10
