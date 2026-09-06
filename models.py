from typing import List
from pydantic import BaseModel, Field

# Represents a suspect, entity, or node in the network
class EntityNode(BaseModel):
    id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    phone_numbers: List[str] = Field(default_factory=list)
    entity_type: str = "PERSON"
    base_risk_score: float = 0.0

# Represents an evidence-backed connection between entities
class EvidenceEdge(BaseModel):
    source_id: str
    target_id: str
    relation_type: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    evidence_source: str

# Output format for the ISO 27005 risk calculation
class RiskAssessment(BaseModel):
    entity_id: str
    threat_score: float = Field(..., ge=0.0, le=100.0)
    risk_level: str
    contributing_factors: List[str] = Field(default_factory=list)

# Schema for tamper-proof hash logging
class AuditLogEntry(BaseModel):
    timestamp: str
    actor_id: str
    action: str
    case_id: str
    previous_hash: str
    current_hash: str