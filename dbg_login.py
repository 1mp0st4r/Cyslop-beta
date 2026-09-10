import os

os.environ["ALLOW_INSECURE_DEV"] = "1"
os.environ.setdefault("CYSLOP_ENV", "dev")
import main
from fastapi.testclient import TestClient

c = TestClient(main.app)
r = c.post("/api/v1/auth/login", json={"badge_id": "OFFICER-4402", "password": "demo-only-change-me"})
print(r.status_code, r.text[:300])
