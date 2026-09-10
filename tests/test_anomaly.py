"""Feature 4 — statistical anomaly detection: 4 detectors, fallback honesty, normals clean.

Own case (CAS-2026-104). Seeding happens inside the first test (not at
import) because entity/edge ids are global PKs: importing `main` during
collection re-seeds the same ids into CAS-2026-102, so seeding must run
after all collection, i.e. at test time.
"""
import os

os.environ.setdefault("ALLOW_INSECURE_DEV", "1")
os.environ.setdefault("CYSLOP_ENV", "dev")
os.environ.setdefault("CYSLOP_DB_PATH", "/tmp/cyslop_test_anomaly.db")
os.environ.setdefault("CYSLOP_ANCHOR_PATH", "/tmp/cyslop_test_anomaly_anchor.json")
for _f in ("/tmp/cyslop_test_anomaly.db", "/tmp/cyslop_test_anomaly_anchor.json"):
    try:
        os.remove(_f)
    except OSError:
        pass

from database import init_db  # noqa: E402

init_db()

import anomaly  # noqa: E402
import patterns  # noqa: E402

CASE = "CAS-2026-104"


def _findings():
    return patterns.list_findings(CASE)


def test_scan_emits_all_four_anomaly_types():
    anomaly.seed_anomalies(CASE)  # test-time seed (see docstring)
    patterns.ensure_findings_table()
    patterns.scan_case(CASE)
    rules = {f["rule_id"] for f in _findings()}
    assert {"A1_amount_outlier", "A2_volume_spike",
            "A3_counterparty_expansion", "A4_odd_hour_activity"} <= rules


def test_anomaly_explanations():
    rows = _findings()
    a1 = [f for f in rows if f["rule_id"] == "A1_amount_outlier"
          and "A1-S" in f["entity_ids"]]
    assert a1 and "z=" in a1[0]["explanation"]
    a2 = [f for f in rows if f["rule_id"] == "A2_volume_spike"
          and f["entity_ids"] == ["A2-S"]]
    assert a2 and "median" in a2[0]["explanation"]
    a3 = [f for f in rows if f["rule_id"] == "A3_counterparty_expansion"]
    assert a3 and "A3-EXP" in a3[0]["entity_ids"] \
        and "new contacts" in a3[0]["explanation"]
    a4 = [f for f in rows if f["rule_id"] == "A4_odd_hour_activity"
          and "A4-N" in f["entity_ids"]]
    assert a4 and "00" in a4[0]["explanation"]
    for f in rows:
        if f["rule_id"].startswith("A"):
            assert f["evidence"], f["rule_id"]
            assert f["severity"] in ("low", "medium", "high")


def test_a2_fallback_names_baseline():
    rows = [f for f in _findings() if f["rule_id"] == "A2_volume_spike"
            and f["entity_ids"] == ["A2-NEW"]]
    assert rows, "expected the low-observation A2 fallback finding"
    assert "fallback" in rows[0]["explanation"]


def test_normals_produce_no_findings():
    rows = _findings()
    assert not [f for f in rows if "A0-N1" in f["entity_ids"]]
    assert not [f for f in rows if "A0-N2" in f["entity_ids"]]


def test_rescan_no_duplicates():
    assert patterns.scan_case(CASE)["new_count"] == 0
