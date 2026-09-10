"""Acceptance check for F3: seed, scan, dedup, dismiss, no-P4-false-positive."""
import os

os.environ.setdefault("CYSLOP_DB_PATH", os.path.join(os.getcwd(), "verify_f3.db"))
if os.path.exists("verify_f3.db"):
    os.remove("verify_f3.db")

import sys, io
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import database
from seed_data import ensure_seed_data

database.init_db()
ensure_seed_data("CAS-2026-102")

import seed_patterns

seed_patterns.CASE = "CAS-2026-102"
seed_patterns.seed()

import patterns

patterns.ensure_findings_table()
r1 = patterns.scan_case("CAS-2026-102")
rules = sorted(x["rule_id"] for x in patterns.list_findings("CAS-2026-102"))
print("scan1 new:", r1["new_count"], "candidates:", r1["candidates"])
print("rules found:", rules)
for f in patterns.list_findings("CAS-2026-102"):
    print(("-", f["rule_id"], f["severity"], f["entity_ids"], "|", f["explanation"][:110]))

assert "P1_circular_flow" in rules, "P1 missing"
assert "P2_burner_hub" in rules, "P2 missing"
assert "P3_call_then_transfer" in rules, "P3 missing"
assert "P4_comm_burst" in rules, "P4 missing"

# steady pair must NOT produce a P4 finding
p4 = [f for f in patterns.list_findings("CAS-2026-102") if f["rule_id"] == "P4_comm_burst"]
assert all("P4-S1" not in f["entity_ids"] for f in p4), "false positive on steady pair"

# re-scan -> no duplicates
r2 = patterns.scan_case("CAS-2026-102")
assert r2["new_count"] == 0, f"dupes on rescan: {r2['new_count']}"
print("rescan new:", r2["new_count"], "OK (no dupes)")

# dismiss persists; rescan doesn't resurrect
fid = patterns.list_findings("CAS-2026-102")[0]["id"]
patterns.set_status(fid, "dismissed")
r3 = patterns.scan_case("CAS-2026-102")
assert r3["new_count"] == 0, "resurrected dismissed finding"
rows = [f for f in patterns.list_findings("CAS-2026-102") if f["id"] == fid]
assert rows and rows[0]["status"] == "dismissed", "dismiss not persisted"
print("dismiss persists OK:", fid)
print("ALL F3 ACCEPTANCE CHECKS PASSED")
