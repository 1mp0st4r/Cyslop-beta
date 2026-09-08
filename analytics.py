"""Phase 3 — Graph analytics.

Centrality ([`nx.pagerank`](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.link_analysis.pagerank_alg.pagerank.html)
+ [`nx.betweenness_centrality`](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.betweenness_centrality.html))
per entity, plus two demoable anomaly patterns:

* Circular money flow — [`nx.simple_cycles()`](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.cycles.simple_cycles.html)
  on the transaction subgraph (TRANSFER / TXN / MONEY edges).
* Burner-phone / multi-contact cluster — entities with call-degree above a
  threshold inside a short time window (parsed from CDR evidence rows).

[`entity_signals()`](analytics.py:1) bundles everything per entity and
[`computed_base_risk()`](analytics.py:1) turns it into a 0-100 score so
[`risk_engine.py`](risk_engine.py:1) no longer needs a hardcoded
`base_risk_score` — ingestion backfills it via
[`recompute_base_risk_scores()`](analytics.py:1).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import networkx as nx

# Relation-type buckets (case-insensitive substring match).
TXN_KEYWORDS = ("TRANSFER", "TXN", "MONEY", "PAYMENT", "TRANSACTION")
CALL_KEYWORDS = ("CALL", "CDR", "PHONE", "CONTACT")

# Demoable defaults: burner fan-out in fixtures is ~17 calls per core phone,
# so 5+ distinct contacts in 72h is a strong, explainable threshold.
DEFAULT_CALL_DEGREE_THRESHOLD = 5
DEFAULT_WINDOW_HOURS = 72


def compute_centrality(g: nx.DiGraph) -> dict[str, dict[str, float]]:
    """PageRank + betweenness per node. Safe on empty/tiny graphs."""
    if g.number_of_nodes() == 0:
        return {"pagerank": {}, "betweenness": {}}
    try:
        pagerank = nx.pagerank(g, weight="weight")
    except Exception:
        pagerank = {n: 1.0 / g.number_of_nodes() for n in g.nodes}
    try:
        betweenness = nx.betweenness_centrality(g, weight="weight", normalized=True)
    except Exception:
        betweenness = {n: 0.0 for n in g.nodes}
    return {
        "pagerank": {k: round(float(v), 4) for k, v in pagerank.items()},
        "betweenness": {k: round(float(v), 4) for k, v in betweenness.items()},
    }


def _is_txn(rel: str) -> bool:
    rel = (rel or "").upper()
    return any(k in rel for k in TXN_KEYWORDS)


def _is_call(rel: str) -> bool:
    rel = (rel or "").upper()
    return any(k in rel for k in CALL_KEYWORDS)


def circular_money_flows(g: nx.DiGraph, max_cycles: int = 25) -> list[list[str]]:
    """Simple cycles on the transaction subgraph (money loops)."""
    txn_edges = [(u, v) for u, v, d in g.edges(data=True) if _is_txn(str(d.get("relation_type", "")))]
    if not txn_edges:
        return []
    sub = nx.DiGraph()
    sub.add_nodes_from(g.nodes(data=True))
    sub.add_edges_from(txn_edges)
    try:
        cycles = list(nx.simple_cycles(sub))
    except Exception:
        return []
    # Shortest / most demoable first, cap for UI payloads.
    cycles.sort(key=len)
    return [list(c) for c in cycles[:max_cycles]]


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=None)
    s = str(value).strip()
    for cand in (s, s.replace("Z", ""), s[:19], s[:10]):
        try:
            return datetime.fromisoformat(cand)
        except ValueError:
            continue
    return None


def burner_clusters(
    raw_edges: list[dict[str, Any]],
    degree_threshold: int = DEFAULT_CALL_DEGREE_THRESHOLD,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> dict[str, dict[str, Any]]:
    """Flag entities with call-degree >= threshold inside a sliding window.

    Uses `evidence_sources.details` JSON (CDR timestamp) when available,
    falling back to the edge `evidence_source` string. Returns
    `{entity_id: {call_degree, window_hours, ...}}` for flagged nodes only.
    """
    # Collect (timestamp, peer) per endpoint over CALL-type edges.
    touches: dict[str, list[tuple[datetime | None, str]]] = defaultdict(list)
    for r in raw_edges:
        if not _is_call(str(r.get("relation_type", ""))):
            continue
        src, dst = r.get("source_id"), r.get("target_id")
        ts = _parse_ts(r.get("timestamp") or r.get("reviewed_at"))
        if ts is None:
            # evidence_source embeds "@ <iso>" for CDR rows; details may hold JSON.
            import json as _json
            import re as _re

            blob = f"{r.get('evidence_source', '')} {r.get('details', '')}"
            m = _re.search(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?)", blob)
            if m:
                ts = _parse_ts(m.group(1))
            else:
                try:
                    ts = _parse_ts(_json.loads(str(r.get("details", "") or "{}")).get("timestamp"))
                except Exception:
                    ts = None
        touches[src].append((ts, dst))
        touches[dst].append((ts, src))

    flagged: dict[str, dict[str, Any]] = {}
    window = timedelta(hours=window_hours)
    for node, events in touches.items():
        peers_all = {p for _, p in events}
        if len(peers_all) < degree_threshold:
            continue  # fast path: never reaches threshold at all
        timed = sorted([e for e in events if e[0] is not None], key=lambda e: e[0])  # type: ignore[index]
        best: set[str] = set()
        if timed:
            # Sliding window over sorted timestamps.
            j = 0
            for i in range(len(timed)):
                while timed[i][0] - timed[j][0] > window:  # type: ignore[operator]
                    j += 1
                peers = {p for _, p in timed[j : i + 1]}
                if len(peers) > len(best):
                    best = peers
        else:
            best = peers_all  # no timestamps: fall back to total distinct contacts
        if len(best) >= degree_threshold:
            flagged[node] = {
                "call_degree": len(best),
                "window_hours": window_hours,
                "reason": (
                    f"Burner/multi-contact pattern: {len(best)} distinct contacts "
                    f"within {window_hours}h (threshold {degree_threshold})."
                ),
            }
    return flagged


def computed_base_risk(
    node: str,
    pagerank: dict[str, float],
    betweenness: dict[str, float],
    cycles: list[list[str]],
    burner: dict[str, dict[str, Any]],
) -> float:
    """Computed 0-100 replacement for the hardcoded `base_risk_score`.

    Formula (explainable, demoable): start at 20, add up to +40 PageRank
    share, +20 betweenness share, +10 per money-cycle membership (cap +20),
    +15 burner flag. Clamped to [5, 95] so ISO tiers still discriminate.
    """
    n = max(len(pagerank), 1)
    pr = float(pagerank.get(node, 0.0))
    bw = float(betweenness.get(node, 0.0))
    score = 20.0 + (pr * n * 40.0) + (bw * 20.0)
    in_cycle = sum(1 for c in cycles if node in c)
    score += min(in_cycle, 2) * 10.0
    if node in burner:
        score += 15.0
    return round(min(max(score, 5.0), 95.0), 1)


def entity_signals(
    g: nx.DiGraph,
    raw_edges: list[dict[str, Any]] | None = None,
    degree_threshold: int = DEFAULT_CALL_DEGREE_THRESHOLD,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> dict[str, dict[str, Any]]:
    """Per-entity bundle consumed by [`risk_engine.py`](risk_engine.py:1)."""
    cent = compute_centrality(g)
    pagerank, betweenness = cent["pagerank"], cent["betweenness"]
    cycles = circular_money_flows(g)
    burner = burner_clusters(raw_edges or [], degree_threshold, window_hours)
    signals: dict[str, dict[str, Any]] = {}
    for node in g.nodes:
        signals[node] = {
            "pagerank": pagerank.get(node, 0.0),
            "betweenness": betweenness.get(node, 0.0),
            "in_money_cycle": any(node in c for c in cycles),
            "money_cycles": [c for c in cycles if node in c],
            "burner_flag": node in burner,
            "burner_detail": burner.get(node),
            "computed_base_risk": computed_base_risk(node, pagerank, betweenness, cycles, burner),
        }
    return signals


def recompute_base_risk_scores(case_id: str) -> dict[str, float]:
    """Backfill `entities.base_risk_score` from graph analytics. Returns map."""
    from database import get_db  # deferred: avoids import cycle
    from graph_store import build_graph, get_edges

    g = build_graph(case_id)
    _, raw_edges = get_edges(case_id)
    signals = entity_signals(g, raw_edges)
    out: dict[str, float] = {}
    with get_db() as conn:
        for node, sig in signals.items():
            out[node] = sig["computed_base_risk"]
            conn.execute(
                "UPDATE entities SET base_risk_score = ? WHERE id = ?",
                (sig["computed_base_risk"], node),
            )
    return out
