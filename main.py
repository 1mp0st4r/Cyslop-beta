from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel

from models import RiskAssessment, AuditLogEntry
from security import get_current_user_role, mask_entity_pii
from risk_engine import calculate_threat_score
from audit_log import log_officer_action, AUDIT_LEDGER, verify_audit_chain
from seed_data import MOCK_ENTITIES, MOCK_EDGES

app = FastAPI(
    title="Criminal Network Analyzer API",
    description="Backend service powering graph analysis, ISO 27005 risk assessment, and tamper-evident audit logging.",
    version="1.0.0"
)

# Review request schema
class LinkReviewRequest(BaseModel):
    link_id: str
    action: str  # "APPROVE" or "REJECT"
    officer_badge: str

class AuthLoginRequest(BaseModel):
    badge_id: str

# 1. Secure Access / Authentication
@app.post("/api/v1/auth/login", tags=["Authentication"])
def login(request: AuthLoginRequest):
    role = "lead_investigator" if "4402" in request.badge_id else "analyst"
    log_officer_action(request.badge_id, "LOGIN_AUTHORIZED", "CAS-2026-102")
    return {
        "status": "AUTHORIZED",
        "badge_id": request.badge_id,
        "assigned_role": role,
        "active_case": "CAS-2026-102"
    }

# 2. Case Overview Metrics
@app.get("/api/v1/cases/{case_id}/overview", tags=["Dashboard"])
def get_case_overview(case_id: str, role: str = Depends(get_current_user_role)):
    log_officer_action(role, "VIEW_CASE_OVERVIEW", case_id)
    return {
        "case_id": case_id,
        "case_title": "Operation Redline",
        "total_suspects": len([e for e in MOCK_ENTITIES.values() if e.entity_type == "PERSON"]),
        "total_phone_numbers": sum(len(e.phone_numbers) for e in MOCK_ENTITIES.values()),
        "total_bank_accounts": len([e for e in MOCK_ENTITIES.values() if e.entity_type == "BANK_ACCOUNT"]),
        "unreviewed_alerts": 3,
        "system_status": "NORMAL",
        "cpu_load_percent": 18.5,
        "memory_usage_percent": 42.1
    }

# 3. Interactive Graph Data (Cytoscape-Ready)
@app.get("/api/v1/cases/{case_id}/graph", tags=["Node Graph"])
def get_network_graph(case_id: str, role: str = Depends(get_current_user_role)):
    log_officer_action(role, "VIEW_NETWORK_GRAPH", case_id)
    
    # Apply dynamic PII masking to node phone numbers based on role
    sanitized_nodes = [
        mask_entity_pii(entity, role) for entity in MOCK_ENTITIES.values()
    ]
    
    return {
        "case_id": case_id,
        "nodes": sanitized_nodes,
        "edges": MOCK_EDGES
    }

# 4. Suspect Threat Scoring (ISO/IEC 27005)
@app.get("/api/v1/suspect/{entity_id}/risk", response_model=RiskAssessment, tags=["Risk Engine"])
def get_suspect_risk(entity_id: str, role: str = Depends(get_current_user_role)):
    if entity_id not in MOCK_ENTITIES:
        raise HTTPException(status_code=404, detail="Entity node not found.")
    
    log_officer_action(role, f"CALCULATE_ISO27005_RISK_{entity_id}", "CAS-2026-102")
    entity = MOCK_ENTITIES[entity_id]
    return calculate_threat_score(entity, MOCK_EDGES)

# 5. Evidence Review / Human-in-the-Loop Validation
@app.post("/api/v1/links/review", tags=["Evidence Inspector"])
def review_link(review: LinkReviewRequest):
    action_verb = "APPROVED_CONNECTION" if review.action.upper() == "APPROVE" else "REJECTED_CONNECTION"
    entry = log_officer_action(review.officer_badge, f"{action_verb}_{review.link_id}", "CAS-2026-102")
    
    return {
        "status": "SUCCESS",
        "link_id": review.link_id,
        "decision": review.action.upper(),
        "audit_hash": entry.current_hash
    }

# 6. Session Termination / Audit Export
@app.post("/api/v1/auth/logout", tags=["Authentication"])
def logout(badge_id: str = "OFFICER-4402"):
    log_officer_action(badge_id, "SESSION_TERMINATED", "CAS-2026-102")
    is_valid = verify_audit_chain()
    
    return {
        "session_status": "TERMINATED",
        "badge_id": badge_id,
        "total_actions_audited": len(AUDIT_LEDGER),
        "chain_integrity_verified": is_valid,
        "ledger": AUDIT_LEDGER
    }