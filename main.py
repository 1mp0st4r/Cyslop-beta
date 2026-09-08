import os
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from models import RiskAssessment, AuditLogEntry
from security import (
    assert_secret_configured, get_current_user, get_current_user_role,
    mask_entity_pii, verify_password, create_access_token, CurrentUser,
    check_lockout, record_login_failure, record_login_success,
)
from risk_engine import calculate_threat_score
from audit_log import (
    log_officer_action, verify_audit_chain, refresh_cache,
    anchor_audit_chain, verify_against_anchor,
)
from seed_data import ensure_seed_data, ensure_seed_users, DEFAULT_CASE_ID
from database import init_db, get_db

assert_secret_configured()

ENV = os.environ.get("CYSLOP_ENV", "production")
_frontends = [o.strip() for o in os.environ.get(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(
    title="Criminal Network Analyzer API",
    description="Backend service powering graph analysis, ISO 27005 risk assessment, JWT auth, and tamper-evident audit logging.",
    version="3.1.0",
    docs_url="/docs" if ENV != "production" else None,
    redoc_url=None if ENV == "production" else "/redoc",
    openapi_url="/openapi.json" if ENV != "production" else None,
)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda req, exc: JSONResponse(status_code=429, content={"detail": "Rate limit exceeded."}),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontends,  # pinned origins; never "*" with credentials
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if ENV == "production":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp

from graph_store import get_entities, get_edges, graph_analytics

# Ensure SQLite schema + demo case + env-provided users at startup.
init_db()
ensure_seed_data(DEFAULT_CASE_ID)
ensure_seed_users()


@app.get("/healthz", tags=["Ops"])
def healthz():
    return {"status": "ok", "env": ENV}


@app.get("/readyz", tags=["Ops"])
def readyz():
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"ready": True}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB not ready: {exc}")

# Review request schema
class LinkReviewRequest(BaseModel):
    link_id: str
    action: str  # "APPROVE" or "REJECT"
    officer_badge: str

class AuthLoginRequest(BaseModel):
    badge_id: str
    password: str


def _do_login(badge_id: str, password: str, client_key: str):
    check_lockout(f"{client_key}:{badge_id}")
    with get_db() as conn:
        row = conn.execute(
            "SELECT badge_id, password_hash, role, active_case FROM users WHERE badge_id = ?",
            (badge_id,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        record_login_failure(f"{client_key}:{badge_id}")
        try:
            log_officer_action(badge_id, "LOGIN_FAILED", "CAS-2026-102")
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid badge ID or access key.")
    record_login_success(f"{client_key}:{badge_id}")
    token = create_access_token(row["badge_id"], row["role"], row["active_case"])
    log_officer_action(row["badge_id"], "LOGIN_AUTHORIZED", row["active_case"])
    return {
        "status": "AUTHORIZED",
        "badge_id": row["badge_id"],
        "assigned_role": row["role"],
        "active_case": row["active_case"],
        "access_token": token,
        "token_type": "bearer",
    }

# 1. Secure Access / Authentication (rate-limited: 10/min per IP)
@app.post("/api/v1/auth/login", tags=["Authentication"])
@limiter.limit("10/minute")
def login(request: Request, body: AuthLoginRequest):
    return _do_login(body.badge_id, body.password, get_remote_address(request))


@app.post("/api/v1/auth/token", tags=["Authentication"])
@limiter.limit("10/minute")
def oauth_token(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password flow alias (Swagger 'Authorize' button support)."""
    return _do_login(form.username, form.password, get_remote_address(request))


@app.get("/api/v1/auth/me", tags=["Authentication"])
def me(user: CurrentUser = Depends(get_current_user)):
    return {"badge_id": user.badge_id, "role": user.role, "active_case": user.active_case}

# 2. Case Overview Metrics (DB-backed)
@app.get("/api/v1/cases/{case_id}/overview", tags=["Dashboard"])
def get_case_overview(case_id: str, role: str = Depends(get_current_user_role)):
    log_officer_action(role, "VIEW_CASE_OVERVIEW", case_id)
    entities = get_entities(case_id)
    return {
        "case_id": case_id,
        "case_title": "Operation Redline",
        "total_suspects": len([e for e in entities if e.entity_type == "PERSON"]),
        "total_phone_numbers": sum(len(e.phone_numbers) for e in entities),
        "total_bank_accounts": len([e for e in entities if e.entity_type == "BANK_ACCOUNT"]),
        "unreviewed_alerts": 3,
        "system_status": "NORMAL",
        "cpu_load_percent": 18.5,
        "memory_usage_percent": 42.1
    }

# 3. Interactive Graph Data (Cytoscape-Ready, DB + NetworkX)
@app.get("/api/v1/cases/{case_id}/graph", tags=["Node Graph"])
def get_network_graph(case_id: str, role: str = Depends(get_current_user_role)):
    log_officer_action(role, "VIEW_NETWORK_GRAPH", case_id)
    entities = get_entities(case_id)
    _, raw_edges = get_edges(case_id)
    sanitized_nodes = [mask_entity_pii(entity, role) for entity in entities]
    edges = [
        {"link_id": r["id"], "source_id": r["source_id"], "target_id": r["target_id"],
         "relation_type": r["relation_type"], "confidence_score": r["confidence_score"],
         "evidence_source": r["evidence_source"], "status": r["status"]}
        for r in raw_edges
    ]
    return {"case_id": case_id, "nodes": sanitized_nodes, "edges": edges}

# 3b. Graph analytics: PageRank / betweenness / cycles
@app.get("/api/v1/cases/{case_id}/graph/analytics", tags=["Node Graph"])
def get_graph_analytics(case_id: str, role: str = Depends(get_current_user_role)):
    log_officer_action(role, "VIEW_GRAPH_ANALYTICS", case_id)
    return {"case_id": case_id, **graph_analytics(case_id)}

# 3c. Phase-2 ingestion: synthetic fixtures -> graph (lead only in production)
@app.post("/api/v1/cases/{case_id}/ingest", tags=["Ingestion"])
def ingest_case(case_id: str, user: CurrentUser = Depends(get_current_user),
                model: str = "en_core_web_sm"):
    if ENV == "production" and user.role != "lead_investigator":
        raise HTTPException(status_code=403, detail="Only lead_investigator can ingest.")
    from pathlib import Path
    from ingestion.build_graph import ingest_synthetic_dir
    log_officer_action(user.badge_id, "INGEST_SYNTHETIC_DATA", case_id)
    synth = Path(__file__).resolve().parent / "fixtures" / "synthetic"
    return ingest_synthetic_dir(synth, case_id, model)

# 4. Suspect Threat Scoring (ISO/IEC 27005, DB-backed + Phase-3 signals)
@app.get("/api/v1/suspect/{entity_id}/risk", response_model=RiskAssessment, tags=["Risk Engine"])
def get_suspect_risk(entity_id: str, role: str = Depends(get_current_user_role)):
    entities = {e.id: e for e in get_entities(DEFAULT_CASE_ID)}
    if entity_id not in entities:
        raise HTTPException(status_code=404, detail="Entity node not found.")
    log_officer_action(role, f"CALCULATE_ISO27005_RISK_{entity_id}", "CAS-2026-102")
    entity = entities[entity_id]
    pydantic_edges, _ = get_edges(DEFAULT_CASE_ID)
    try:
        signals = graph_analytics(DEFAULT_CASE_ID).get("signals", {}).get(entity_id)
    except Exception:
        signals = None
    return calculate_threat_score(entity, pydantic_edges, signals)

# 4b. Pending review queue (PENDING edges across a case)
@app.get("/api/v1/cases/{case_id}/links/pending", tags=["Evidence Inspector"])
def pending_links(case_id: str, role: str = Depends(get_current_user_role)):
    _, raw_edges = get_edges(case_id)
    pending = [e for e in raw_edges if str(e.get("status", "")).upper() in ("PENDING", "PENDING_REVIEW", "UNREVIEWED")]
    return {"case_id": case_id, "count": len(pending), "links": pending}

# 5. Evidence Review / Human-in-the-Loop Validation (persisted status + audit, JWT identity)
@app.post("/api/v1/links/review", tags=["Evidence Inspector"])
def review_link(review: LinkReviewRequest, user: CurrentUser = Depends(get_current_user)):
    from datetime import datetime, timezone
    actor = user.badge_id
    if review.officer_badge and review.officer_badge != actor:
        raise HTTPException(status_code=403, detail="officer_badge must match authenticated user.")
    action_verb = "APPROVED_CONNECTION" if review.action.upper() == "APPROVE" else "REJECTED_CONNECTION"
    entry = log_officer_action(actor, f"{action_verb}_{review.link_id}", "CAS-2026-102")
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE edges SET status = ?, reviewer = ?, reviewed_at = ? WHERE id = ?",
            (review.action.upper(), actor,
             datetime.now(timezone.utc).isoformat(), review.link_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Link id not found.")
    return {
        "status": "SUCCESS",
        "link_id": review.link_id,
        "decision": review.action.upper(),
        "audit_hash": entry.current_hash
    }

# 6. Session Termination / Audit Export (persisted chain + anchor)
@app.post("/api/v1/auth/logout", tags=["Authentication"])
def logout(user: CurrentUser = Depends(get_current_user)):
    log_officer_action(user.badge_id, "SESSION_TERMINATED", user.active_case)
    anchor = anchor_audit_chain()
    is_valid = verify_audit_chain()
    ledger = refresh_cache()
    return {
        "session_status": "TERMINATED",
        "badge_id": user.badge_id,
        "total_actions_audited": len(ledger),
        "chain_integrity_verified": is_valid,
        "anchored_hash": anchor.get("latest_hash"),
        "ledger": ledger
    }

# 7. Audit verification endpoint (chain-of-custody proof + anchor check)
@app.get("/api/v1/cases/{case_id}/audit/verify", tags=["Audit"])
def verify_case_audit(case_id: str, role: str = Depends(get_current_user_role)):
    log_officer_action(role, "VERIFY_AUDIT_CHAIN", case_id)
    ledger = refresh_cache(case_id)
    return {
        "case_id": case_id,
        "chain_integrity_verified": verify_audit_chain(case_id),
        "anchor": verify_against_anchor(),
        "total_entries": len(ledger),
        "entries": ledger,
    }


@app.post("/api/v1/cases/{case_id}/audit/anchor", tags=["Audit"])
def anchor_case_audit(case_id: str, user: CurrentUser = Depends(get_current_user)):
    if user.role != "lead_investigator":
        raise HTTPException(status_code=403, detail="Only lead_investigator can anchor the ledger.")
    log_officer_action(user.badge_id, "ANCHOR_AUDIT_CHAIN", case_id)
    return {"case_id": case_id, **anchor_audit_chain()}
