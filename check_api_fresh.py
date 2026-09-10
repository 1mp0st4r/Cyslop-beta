import os

os.environ["ALLOW_INSECURE_DEV"] = "1"
os.environ["CYSLOP_DEMO_PASSWORD"] = "demo-only-change-me"
os.environ["CYSLOP_ENV"] = "dev"
os.environ["CYSLOP_DB_PATH"] = os.path.join(os.getcwd(), "check_f3.db")
for f in ("check_f3.db",):
    try:
        os.remove(f)
    except OSError:
        pass
import main
from fastapi.testclient import TestClient

c = TestClient(main.app)
r = c.post("/api/v1/auth/login", json={"badge_id": "OFFICER-4402", "password": "demo-only-change-me"})
assert r.status_code == 200, r.text
h = {"Authorization": f"Bearer {r.json()['access_token']}"}
s = c.post("/patterns/scan/CAS-2026-102", headers=h)
print("scan:", s.status_code, s.json().get("new_count"), "candidates:", s.json().get("candidates"))
assert s.status_code == 200
f = c.get("/findings/CAS-2026-102", headers=h)
rules = sorted(x["rule_id"] for x in f.json()["findings"])
print("rules:", rules)
assert rules == ["P1_circular_flow", "P2_burner_hub", "P3_call_then_transfer", "P4_comm_burst"], rules
assert c.post("/patterns/scan/CAS-2026-102", headers=h).json()["new_count"] == 0
fid = f.json()["findings"][0]["id"]
assert c.post(f"/findings/{fid}/dismiss", headers=h).status_code == 200
assert c.post("/patterns/scan/CAS-2026-102", headers=h).json()["new_count"] == 0
st = [x for x in c.get("/findings/CAS-2026-102", headers=h).json()["findings"] if x["id"] == fid][0]["status"]
assert st == "dismissed", st
print("open count:", c.get("/findings/CAS-2026-102?status=open", headers=h).json()["count"])
print("API CHECKS PASSED")
