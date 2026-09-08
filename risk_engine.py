from typing import Any, Dict, List, Optional, Tuple
from models import EntityNode, EvidenceEdge, RiskAssessment

# Phase 3: per-entity graph signals from analytics.entity_signals()
# {pagerank, betweenness, in_money_cycle, burner_flag, computed_base_risk, ...}
GraphSignals = Optional[Dict[str, Any]]

# ISO/IEC 27005:2022 Annex A, Table A.3: Qualitative Risk Matrix
# Maps (Likelihood 1-5, Consequence 1-5) -> Qualitative Risk Tier
ISO_27005_RISK_MATRIX = {
    # (Likelihood, Consequence): Tier
    (5, 5): "VERY HIGH", (5, 4): "VERY HIGH", (5, 3): "HIGH",      (5, 2): "HIGH",   (5, 1): "MEDIUM",
    (4, 5): "VERY HIGH", (4, 4): "HIGH",      (4, 3): "HIGH",      (4, 2): "MEDIUM", (4, 1): "LOW",
    (3, 5): "HIGH",      (3, 4): "HIGH",      (3, 3): "MEDIUM",    (3, 2): "LOW",    (3, 1): "LOW",
    (2, 5): "MEDIUM",    (2, 4): "MEDIUM",    (2, 3): "LOW",       (2, 2): "LOW",    (2, 1): "VERY LOW",
    (1, 5): "LOW",       (1, 4): "LOW",       (1, 3): "LOW",       (1, 2): "VERY LOW",(1, 1): "VERY LOW",
}

def _assess_likelihood(edges: List[EvidenceEdge], signals: GraphSignals = None) -> Tuple[int, List[str]]:
    """Evaluates Likelihood (1-5) per ISO 27005 Clause 7.3.3 & Table A.2.

    Phase 3: graph signals (burner fan-out, money-cycle membership,
    betweenness) boost the score instead of relying on raw edge counts alone.
    """
    factors = []
    signals = signals or {}
    if not edges:
        return 1, ["No active evidence connections identified (Likelihood: Unlikely)."]

    # Average evidence confidence across graph edges
    avg_confidence = sum(e.confidence_score for e in edges) / len(edges)
    connection_count = len(edges)

    # Corroboration increases probability of threat materialization
    if connection_count >= 5 or avg_confidence >= 0.85:
        score = 5
        desc = "Almost certain: Dense evidence network with high corroboration."
    elif connection_count >= 3 or avg_confidence >= 0.70:
        score = 4
        desc = "Very likely: Multiple verified links identified."
    elif connection_count >= 2:
        score = 3
        desc = "Likely: Recurring evidence links detected."
    elif connection_count == 1:
        score = 2
        desc = "Rather unlikely: Single isolated evidence edge."
    else:
        score = 1
        desc = "Unlikely: Minimal observed activity."

    # --- Phase 3 anomaly boosts (capped at 5) ---
    if signals.get("burner_flag"):
        score = min(5, score + 1)
        detail = (signals.get("burner_detail") or {}).get("reason", "Burner/multi-contact cluster.")
        factors.append(f"Anomaly boost: {detail} (+1 likelihood).")
    if signals.get("in_money_cycle"):
        score = min(5, score + 1)
        factors.append("Anomaly boost: entity sits on a circular money-flow cycle (+1 likelihood).")
    if float(signals.get("betweenness", 0.0)) >= 0.15 and score < 5:
        score = min(5, score + 1)
        factors.append(
            f"Centrality boost: betweenness {float(signals.get('betweenness', 0.0)):.3f} "
            "marks a bridge/broker node (+1 likelihood)."
        )

    factors.append(f"Likelihood Level {score}/5 - {desc}")
    return score, factors

def _assess_consequence(
    entity: EntityNode, edges: List[EvidenceEdge], signals: GraphSignals = None
) -> Tuple[int, List[str]]:
    """Evaluates Consequence (1-5) per ISO 27005 Clause 7.3.2 & Table A.1.

    Phase 3: prefers the computed `signals["computed_base_risk"]`
    (PageRank + betweenness + anomalies) over the stored hardcoded
    `base_risk_score`; falls back to the stored value when no signals given.
    """
    factors = []
    consequence_score = 1
    signals = signals or {}

    # Computed severity wins; stored value is the fallback.
    base_risk = float(signals.get("computed_base_risk", entity.base_risk_score))
    if "computed_base_risk" in signals:
        factors.append(
            f"Computed base risk {base_risk:.1f}/100 from PageRank "
            f"{float(signals.get('pagerank', 0.0)):.4f} + betweenness "
            f"{float(signals.get('betweenness', 0.0)):.4f}"
            + (" + money-cycle membership" if signals.get("in_money_cycle") else "")
            + (" + burner-cluster flag" if signals.get("burner_flag") else "")
            + "."
        )

    # Check entity base severity (e.g. prior FIR flags, syndicate rank)
    if base_risk >= 80:
        consequence_score = max(consequence_score, 5)
        factors.append("Consequence Level 5/5: Catastrophic impact (Major syndicate target / high-priority warrant).")
    elif base_risk >= 60:
        consequence_score = max(consequence_score, 4)
        factors.append("Consequence Level 4/5: Critical operational disruption.")
    elif base_risk >= 40:
        consequence_score = max(consequence_score, 3)
        factors.append("Consequence Level 3/5: Serious security concern.")

    # Elevate consequence if high-risk transfer anomalies are present
    suspicious_edges = [e for e in edges if "SUSPICIOUS" in e.relation_type.upper()]
    if suspicious_edges:
        consequence_score = min(5, consequence_score + len(suspicious_edges))
        factors.append(f"Elevated by {len(suspicious_edges)} illicit transaction/call anomalies (Table A.12).")

    if consequence_score == 1:
        factors.append("Consequence Level 1/5: Minor organizational or network impact.")

    return consequence_score, factors

def calculate_threat_score(
    entity: EntityNode,
    edges: List[EvidenceEdge],
    signals: GraphSignals = None,
) -> RiskAssessment:
    """
    Executes an ISO/IEC 27005 Clause 7 Risk Assessment.
    Combines Likelihood and Consequence via Table A.3 matrix and outputs Table A.6 tiers.
    `signals` is the per-entity dict from analytics.entity_signals(); when
    omitted the engine falls back to the legacy hardcoded behaviour.
    """
    # 1. Filter edges associated with this entity
    connected_edges = [
        e for e in edges if e.source_id == entity.id or e.target_id == entity.id
    ]

    # 2. Derive ISO parameters (Phase 3: graph-signal aware)
    likelihood, l_factors = _assess_likelihood(connected_edges, signals)
    consequence, c_factors = _assess_consequence(entity, connected_edges, signals)

    # 3. Determine Level of Risk from ISO 27005 Matrix (Table A.3)
    iso_tier = ISO_27005_RISK_MATRIX.get((likelihood, consequence), "MEDIUM")

    # 4. Map matrix cell to a continuous 0-100 display score for the UI
    raw_score = ((likelihood * 0.5) + (consequence * 0.5)) * 20.0
    threat_score = min(max(round(raw_score, 1), 0.0), 100.0)

    # 5. Classify according to Table A.6 (Evaluation Scale / 3-Colour Model)
    if iso_tier in ["VERY HIGH", "HIGH"]:
        risk_level = "HIGH"    # Red: Unacceptable, mandatory officer review
    elif iso_tier == "MEDIUM":
        risk_level = "MEDIUM"  # Amber: Tolerable under monitoring
    else:
        risk_level = "LOW"     # Green: Acceptable as is

    all_factors = l_factors + c_factors
    all_factors.append(f"ISO/IEC 27005 Assessment Matrix Tier: {iso_tier} (Likelihood: {likelihood}, Consequence: {consequence})")

    return RiskAssessment(
        entity_id=entity.id,
        threat_score=threat_score,
        risk_level=risk_level,
        contributing_factors=all_factors
    )