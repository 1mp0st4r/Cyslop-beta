import os

os.environ["ALLOW_INSECURE_DEV"] = "1"
os.environ.setdefault("CYSLOP_ENV", "dev")
import main
from fastapi.testclient import TestClient

c = TestClient(main.app)
tok = c.post("/api/v1/auth/login", json={"badge_id": "OFFICER-4402", "password": "demo-only-change-me"}).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
r = c.post("/patterns/scan/CAS-2026-102", headers=h)
print("scan:", r.status_code, r.json().get("new_count"), "candidates:", r.json().get("candidates"))
r = c.get("/findings/CAS-2026-102", headers=h)
print("findings:", r.status_code, r.json().get("count"), sorted(f["rule_id"] for f in r.json()["findings"]))
r2 = c.post("/patterns/scan/CAS-2026-102", headers=h)
print("rescan new:", r2.json().get("new_count"))
assert r2.json()["new_count"] == 0
fid = r.json()["findings"][0]["id"]
print("dismiss:", c.post(f"/findings/{fid}/dismiss", headers=h).status_code)
r3 = c.post("/patterns/scan/CAS-2026-102", headers=h)
assert r3.json()["new_count"] == 0
st = [f for f in c.get("/findings/CAS-2026-102", headers=h).json()["findings"] if f["id"] == fid][0]["status"]
assert st == "dismissed", st
print("filtered:", c.get("/findings/CAS-2026-102?status=open", headers=h).json().get("count"))
print("API CHECKS PASSED")
