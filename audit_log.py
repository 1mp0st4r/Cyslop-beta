import hashlib
from datetime import datetime, timezone
from typing import List
from models import AuditLogEntry

# In-memory append-only ledger for the session
AUDIT_LEDGER: List[AuditLogEntry] = []

# Genesis hash for the start of the chain
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

def _compute_hash(timestamp: str, actor_id: str, action: str, case_id: str, prev_hash: str) -> str:
    """Computes a SHA-256 cryptographic digest of the entry data."""
    payload = f"{timestamp}|{actor_id}|{action}|{case_id}|{prev_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def log_officer_action(actor_id: str, action: str, case_id: str) -> AuditLogEntry:
    """
    Records an action into the immutable hash chain.
    Satisfies chain-of-custody requirements for evidence admissibility.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Retrieve previous hash or use genesis
    prev_hash = AUDIT_LEDGER[-1].current_hash if AUDIT_LEDGER else GENESIS_HASH
    
    curr_hash = _compute_hash(timestamp, actor_id, action, case_id, prev_hash)
    
    entry = AuditLogEntry(
        timestamp=timestamp,
        actor_id=actor_id,
        action=action,
        case_id=case_id,
        previous_hash=prev_hash,
        current_hash=curr_hash
    )
    
    AUDIT_LEDGER.append(entry)
    return entry

def verify_audit_chain() -> bool:
    """Validates that no historical log entry has been altered or tampered with."""
    for i in range(len(AUDIT_LEDGER)):
        expected_prev = GENESIS_HASH if i == 0 else AUDIT_LEDGER[i - 1].current_hash
        if AUDIT_LEDGER[i].previous_hash != expected_prev:
            return False
            
        recalculated = _compute_hash(
            AUDIT_LEDGER[i].timestamp,
            AUDIT_LEDGER[i].actor_id,
            AUDIT_LEDGER[i].action,
            AUDIT_LEDGER[i].case_id,
            AUDIT_LEDGER[i].previous_hash
        )
        if AUDIT_LEDGER[i].current_hash != recalculated:
            return False
            
    return True