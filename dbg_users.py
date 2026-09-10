from database import get_db

with get_db() as conn:
    for r in conn.execute("SELECT badge_id, role, active_case FROM users"):
        print(dict(r))
