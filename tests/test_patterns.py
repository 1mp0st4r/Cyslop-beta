"""Feature 3 — pattern detection acceptance: 4 rules, dedup, dismiss, no P4 FP."""
import os

os.environ.setdefault("ALLOW_INSECURE_DEV", "1")
os.environ.setdefault("CYSLOP_ENV", "dev")
os.environ.setdefault("CYSLOP_DB_PATH", "/tmp/cyslop_test_patterns.db")
os.environ.setdefault("CYSLOP_ANCHOR_PATH", "/tmp/cyslop_test_patterns_anchor.json")
for _f in ("/tmp/cyslop_test_patterns.db", "/tmp/cyslop_test_patterns_anchor.json"):
    try:
        os.remove(_f)
    except OSError:
        pass

from database import init_db  # noqa: E402
from seed_data import ensure_seed_data  # noqa: E402

init_db()
ensure_seed_data("CAS-2026-102")

import seed_patterns  # noqa: E402

seed_patterns.seed()

import patterns  # noqa: E402


def test_scan_finds_all_four_rules():
    patterns.ensure_findings_table()
    out = patterns.scan_case("CAS-2026-102")
    assert out["new_count"] >= 4
    rules = {f["rule_id"] for f in patterns.list_findings("CAS-2026-102")}
    assert {"P1_circular_flow", "P2_burner_hub",
            "P3_call_then_transfer", "P4_comm_burst"} <= rules


def test_entities_and_evidence_present():
    rows = {f["rule_id"]: f for f in patterns.list_findings("CAS-2026-102")}
    assert set(rows["P1_circular_flow"]["entity_ids"]) == {"P1-A", "P1-B", "P1-C"}
    assert "P2-HUB" in rows["P2_burner_hub"]["entity_ids"]
    assert set(rows["P3_call_then_transfer"]["entity_ids"]) == {"P3-A", "P3-B"}
    assert set(rows["P4_comm_burst"]["entity_ids"]) == {"P4-A", "P4-B"}
    for f in rows.values():
        assert f["evidence"], f["rule_id"]
        assert f["explanation"], f["rule_id"]


def test_rescan_no_duplicates_and_dismiss_persists():
    assert patterns.scan_case("CAS-2026-102")["new_count"] == 0
    fid = patterns.list_findings("CAS-2026-102")[0]["id"]
    patterns.set_status(fid, "dismissed")
    assert patterns.scan_case("CAS-2026-102")["new_count"] == 0
    row = [f for f in patterns.list_findings("CAS-2026-102") if f["id"] == fid][0]
    assert row["status"] == "dismissed"
    patterns.set_status(fid, "open")


def test_steady_pair_produces_no_p4():
    p4 = [f for f in patterns.list_findings("CAS-2026-102")
          if f["rule_id"] == "P4_comm_burst"]
    assert p4, "expected the seeded burst finding"
    assert all("P4-S1" not in f["entity_ids"] for f in p4)
