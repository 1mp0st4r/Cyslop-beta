"""Graph store — NetworkX over SQLite rows.

Builds a [`DiGraph`](https://networkx.org) per case from the `entities` /
`edges` tables in [`database.py`](database.py:1) and exposes the analytics
the API needs: PageRank, betweenness centrality, and cycle detection
(money-loop / circular-call patterns). All writes go to SQLite; the
NetworkX graph is rebuilt on demand so it never drifts from storage.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from database import dumps_list, get_db, loads_list
from models import EntityNode, EvidenceEdge


def upsert_entity(entity: EntityNode, case_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO entities (id, case_id, name, aliases, phone_numbers,
                                     entity_type, base_risk_score)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 case_id=excluded.case_id, name=excluded.name,
                 aliases=excluded.aliases, phone_numbers=excluded.phone_numbers,
                 entity_type=excluded.entity_type,
                 base_risk_score=excluded.base_risk_score""",
            (entity.id, case_id, entity.name, dumps_list(entity.aliases),
             dumps_list(entity.phone_numbers), entity.entity_type,
             entity.base_risk_score),
        )


def upsert_edge(edge: EvidenceEdge, case_id: str, link_id: str | None = None,
                status: str = "PENDING") -> str:
    eid = link_id or f"{edge.source_id}->{edge.target_id}:{edge.relation_type}"
    with get_db() as conn:
        conn.execute(
            """INSERT INTO edges (id, case_id, source_id, target_id, relation_type,
                                  confidence_score, evidence_source, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                  case_id=excluded.case_id, source_id=excluded.source_id,
                  target_id=excluded.target_id, relation_type=excluded.relation_type,
                  confidence_score=excluded.confidence_score,
                  evidence_source=excluded.evidence_source,
                  status=excluded.status""",
            (eid, case_id, edge.source_id, edge.target_id, edge.relation_type,
             edge.confidence_score, edge.evidence_source, status),
        )
    return eid


def get_entities(case_id: str) -> list[EntityNode]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM entities WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    return [EntityNode(
        id=r["id"], name=r["name"], aliases=loads_list(r["aliases"]),
        phone_numbers=loads_list(r["phone_numbers"]),
        entity_type=r["entity_type"], base_risk_score=r["base_risk_score"],
    ) for r in rows]


def get_edges(case_id: str) -> tuple[list[EvidenceEdge], list[dict[str, Any]]]:
    """Returns (pydantic edges for risk engine, raw rows with link ids)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM edges WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    pydantic_edges, raw = [], []
    for r in rows:
        pydantic_edges.append(EvidenceEdge(
            source_id=r["source_id"], target_id=r["target_id"],
            relation_type=r["relation_type"],
            confidence_score=r["confidence_score"],
            evidence_source=r["evidence_source"]))
        raw.append(dict(r))
    return pydantic_edges, raw


def build_graph(case_id: str) -> nx.DiGraph:
    g = nx.DiGraph()
    for e in get_entities(case_id):
        g.add_node(e.id, **e.model_dump())
    _, raw_edges = get_edges(case_id)
    for r in raw_edges:
        g.add_edge(r["source_id"], r["target_id"],
                   weight=r["confidence_score"],
                   relation_type=r["relation_type"],
                   link_id=r["id"], status=r["status"])
    return g


def graph_analytics(case_id: str) -> dict[str, Any]:
    """Phase 3: PageRank + betweenness + money-cycles + burner clusters.

    Delegates to [`analytics.py`](analytics.py:1) so the API, the risk
    engine, and ingestion all share one implementation. Safe on empty graphs.
    """
    from analytics import burner_clusters, circular_money_flows, compute_centrality, entity_signals

    g = build_graph(case_id)
    if g.number_of_nodes() == 0:
        return {"pagerank": {}, "betweenness": {}, "cycles": [],
                "money_cycles": [], "burner_clusters": {}, "signals": {},
                "node_count": 0, "edge_count": 0}
    _, raw_edges = get_edges(case_id)
    cent = compute_centrality(g)
    try:
        cycles = list(nx.simple_cycles(g))
    except Exception:
        cycles = []
    money_cycles = circular_money_flows(g)
    burner = burner_clusters(raw_edges)
    signals = entity_signals(g, raw_edges)
    return {
        "pagerank": cent["pagerank"],
        "betweenness": cent["betweenness"],
        "cycles": cycles,
        "money_cycles": money_cycles,
        "burner_clusters": burner,
        "signals": signals,
        "node_count": g.number_of_nodes(),
        "edge_count": g.number_of_edges(),
    }
