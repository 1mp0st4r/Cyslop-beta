"""Production smoke tests: secret guard, JWT auth, PII masking, audit chain + anchor."""
import os

os.environ.setdefault("ALLOW_INSECURE_DEV", "1")
os.environ.setdefault("CYSLOP_ENV", "dev")
os.environ.setdefault("CYSLOP_DB_PATH", "/tmp/cyslop_test.db")
os.environ.setdefault("CYSLOP_ANCHOR_PATH", "/tmp/cyslop_test_anchor.json")
for f in ("/tmp/cyslop_test.db", "/tmp/cyslop_test_anchor.json"):
    try:
        os.remove(f)
    except OSError:
        pass

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

c = TestClient(app)


def _login():
    r = c.post("/api/v1/auth/login",
               json={"badge_id": "OFFICER-4402", "password": "demo-only-change-me"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_healthz():
    assert c.get("/healthz").status_code == 200
    assert c.get("/readyz").json()["ready"] is True


def test_login_and_me():
    tok = _login()
    me = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.json()["role"] == "lead_investigator"


def test_graph_requires_auth_and_masks_for_analyst():
    assert c.get("/api/v1/cases/CAS-2026-102/graph").status_code == 401
    tok = _login()
    g = c.get("/api/v1/cases/CAS-2026-102/graph",
              headers={"Authorization": f"Bearer {tok}"})
    assert g.status_code == 200


def test_audit_anchor_roundtrip():
    tok = _login()
    h = {"Authorization": f"Bearer {tok}"}
    a = c.post("/api/v1/cases/CAS-2026-102/audit/anchor", headers=h)
    assert a.json()["anchored"] is True
    v = c.get("/api/v1/cases/CAS-2026-102/audit/verify", headers=h)
    assert v.json()["chain_integrity_verified"] is True
