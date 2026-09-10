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


# ---- F1 Entity Resolution (append-only; existing models untouched) ----
from typing import Literal, Optional, Union

ENTITY_TYPES = {"person", "phone", "vehicle", "location", "organization"}


class SourceRef(BaseModel):
    source_type: str  # "fir" | "cdr" | "bank" | "criminal_history" | ...
    record_id: str  # id of the source record
    field: Union[str, None] = None  # which field, if structured
    span: Union[tuple[int, int], list[int], None] = None  # char offsets, if extracted from text
    confidence: float = 1.0


class CanonicalEntity(BaseModel):
    id: str  # uuid
    type: Literal["person", "phone", "vehicle", "location", "organization"]
    canonical_name: Optional[str] = None
    attributes: dict = Field(default_factory=dict)  # free-form type-specific attrs
    source_refs: list[SourceRef] = Field(default_factory=list)
    status: Literal["auto", "pending_review", "confirmed"] = "auto"

# ---- F3 Suspicious Pattern Detection (Finding contract for F4/F6/F7) ----
class EvidenceRef(BaseModel):
    edge_id: str = ""
    source_type: str = "EDGE"
    reference: str = ""
    detail: str = ""


class Finding(BaseModel):
    id: str
    rule_id: str
    severity: Literal["low", "medium", "high"] = "medium"  # type: ignore[valid-type]
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    entity_ids: list[str] = Field(default_factory=list)
    explanation: str = ""
    evidence: list["EvidenceRef"] = Field(default_factory=list)  # type: ignore[valid-type]
    detected_at: str = ""
    status: Literal["open", "confirmed", "dismissed"] = "open"  # type: ignore[valid-type]
