"""Production JWT auth (python-jose + passlib), users table with hashed passwords.

Keeps [`mask_entity_pii()`](security.py:130) logic unchanged — it runs off the
`role` claim decoded from a verified JWT. No header fallback exists anymore.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from models import EntityNode

INSECURE_DEFAULT = "dev-only-change-me-in-prod"
SECRET_KEY = os.environ.get("CYSLOP_JWT_SECRET", INSECURE_DEFAULT)
ALLOW_INSECURE_DEV = os.environ.get("ALLOW_INSECURE_DEV", "0") == "1"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("CYSLOP_JWT_EXPIRE_MIN", "480"))


def assert_secret_configured() -> None:
    """Fail fast in production when the JWT secret was never set."""
    if SECRET_KEY == INSECURE_DEFAULT and not ALLOW_INSECURE_DEV:
        raise RuntimeError(
            "CYSLOP_JWT_SECRET is not set. Set a 32+ char secret or "
            "ALLOW_INSECURE_DEV=1 for local demo only."
        )


pwd_context = None
try:
    from passlib.context import CryptContext as _CC
    _ctx = _CC(schemes=["bcrypt"], deprecated="auto")
    # Probe: passlib+bcrypt>=4.0 raises on verify; fall back if broken.
    try:
        _probe_hash = _ctx.hash("probe-test-pw")
        _ctx.verify("probe-test-pw", _probe_hash)
        pwd_context = _ctx
    except Exception:
        pwd_context = None
except Exception:
    pwd_context = None
bearer_scheme = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    badge_id: str
    role: str
    active_case: str = "CAS-2026-102"


class CurrentUser(BaseModel):
    badge_id: str
    role: str
    active_case: str = "CAS-2026-102"


def hash_password(password: str) -> str:
    if pwd_context is not None:
        try:
            return pwd_context.hash(password)
        except Exception:
            pass
    try:
        import bcrypt as _bcrypt
        return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
    except Exception:
        import hashlib as _hl
        import os as _os
        import base64 as _b64
        salt = _b64.b64encode(_os.urandom(16)).decode()
        return "$pbkdf2$" + salt + "$" + _hl.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def verify_password(plain: str, hashed: str) -> bool:
    if pwd_context is not None:
        try:
            return pwd_context.verify(plain, hashed)
        except Exception:
            pass
    try:
        import bcrypt as _bcrypt
        if hashed.startswith("$2"):
            return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        pass
    try:
        if hashed.startswith("$pbkdf2$"):
            import hashlib as _hl
            _, _, salt, digest = hashed.split("$", 3)
            return _hl.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 200_000).hex() == digest
    except Exception:
        pass
    return False


def create_access_token(badge_id: str, role: str, active_case: str = "CAS-2026-102",
                        expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": badge_id, "role": role, "active_case": active_case,
               "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> CurrentUser:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        badge_id: Optional[str] = payload.get("sub")
        role: str = str(payload.get("role", "analyst")).lower()
        if not badge_id or role not in ("lead_investigator", "analyst"):
            raise JWTError("bad claims")
        return CurrentUser(badge_id=badge_id, role=role,
                           active_case=str(payload.get("active_case", "CAS-2026-102")))
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token.",
                            headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """Primary auth dependency — real decoded JWT claim."""
    if creds and creds.credentials:
        return decode_token(creds.credentials)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Not authenticated. Provide Bearer JWT.",
                        headers={"WWW-Authenticate": "Bearer"})


def get_current_user_role(user: CurrentUser = Depends(get_current_user)) -> str:
    """Drop-in replacement for the old header-only dependency."""
    return user.role


def require_role(*allowed: str):
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Insufficient clearance for this action.")
        return user
    return checker


# --- Login brute-force guard (in-memory; use Redis for multi-replica prod) ---
_MAX_FAILS = int(os.environ.get("CYSLOP_LOGIN_MAX_FAILS", "5"))
_LOCKOUT_SECS = int(os.environ.get("CYSLOP_LOGIN_LOCKOUT_SECS", "300"))
_fails: dict[str, tuple[int, float]] = {}


def check_lockout(key: str) -> None:
    fails, locked_until = _fails.get(key, (0, 0.0))
    if fails >= _MAX_FAILS and time.time() < locked_until:
        raise HTTPException(status_code=429,
                            detail="Too many failed logins. Try again later.")


def record_login_failure(key: str) -> None:
    fails, _ = _fails.get(key, (0, 0.0))
    fails += 1
    locked_until = time.time() + _LOCKOUT_SECS if fails >= _MAX_FAILS else 0.0
    _fails[key] = (fails, locked_until)


def record_login_success(key: str) -> None:
    _fails.pop(key, None)


# 2. Data masking function for Personally Identifiable Information (PII)
#    UNCHANGED logic — only the caller changed (JWT claim instead of raw header).
def mask_entity_pii(entity: EntityNode, role: str) -> EntityNode:
    if role == "lead_investigator":
        return entity

    # Analysts receive masked PII
    masked_phones = []
    for phone in entity.phone_numbers:
        if len(phone) >= 6:
            masked = phone[:4] + "******" + phone[-2:]
        else:
            masked = "**********"
        masked_phones.append(masked)

    masked_entity = entity.model_copy()
    masked_entity.phone_numbers = masked_phones
    # Mask name/aliases for non-lead roles (analyst sees initials only).
    def _mask_name(n: str) -> str:
        if not n or len(n.strip()) < 2:
            return "***"
        parts = n.strip().split()
        return " ".join((p[0] + "***") for p in parts)
    masked_entity.name = _mask_name(entity.name)
    masked_entity.aliases = [_mask_name(a) for a in (entity.aliases or [])]
    return masked_entity
