import os

os.environ["ALLOW_INSECURE_DEV"] = "1"
import main

paths = sorted({r.path for r in main.app.routes if hasattr(r, "path") and ("pattern" in r.path or "finding" in r.path)})
print("F3 routes:", paths)
assert "/patterns/scan/{case_id}" in paths
assert "/findings/{case_id}" in paths
assert "/findings/{fid}/confirm" in paths
assert "/findings/{fid}/dismiss" in paths

from fastapi.testclient import TestClient

c = TestClient(main.app)
r = c.post("/patterns/scan/CAS-2026-102")
print("scan status:", r.status_code, r.json().get("new_count"))
r = c.get("/findings/CAS-2026-102")
print("findings count:", r.json().get("count"))
r2 = c.post("/patterns/scan/CAS-2026-102")
print("rescan new:", r2.json().get("new_count"))
fid = r.json()["findings"][0]["id"]
c.post(f"/findings/{fid}/dismiss")
r3 = c.post("/patterns/scan/CAS-2026-102")
print("after dismiss rescan new:", r3.json().get("new_count"))
st = [f for f in c.get("/findings/CAS-2026-102").json()["findings"] if f["id"] == fid][0]["status"]
print("dismissed status:", st)
print("API CHECKS PASSED")
