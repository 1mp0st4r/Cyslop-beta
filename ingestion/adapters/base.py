"""F5 source adapters — BaseAdapter protocol, CanonicalRecord, registry.

Every adapter normalizes its raw payload into ``CanonicalRecord`` objects
which flow through the SAME normalize -> extract (if text) -> resolve ->
graph path established in F1/F2:

- structured records  -> ``entity_resolution.ingest_canonical`` (deterministic
  content-hash node ids => idempotent) + explicit edges via ``graph_store``.
- text records        -> ``extraction.ingest_text`` verbatim (extraction_runs
  dedupe by content hash => idempotent) + adapter-specific post-edges.

Nothing downstream changes: resolution, patterns and anomalies already
operate on generic graph structures.
"""
from __future__ import annotations

import json
from typing import Any, Iterator, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from database import get_db, init_db
from models import CanonicalEntity, EntityNode, SourceRef

# Confidence for adapter-sourced structured edges (documented, citable).
STRUCT_EDGE_CONF = 0.88
OBSERVED_EDGE_CONF = 0.85
COMMUNICATES_CONF = 0.8
ASSOC_CASE_CONF = 0.9


class CanonicalRecord(BaseModel):
    """Normalized output of every adapter; kind drives the pipeline hop."""

    source_type: str
    record_id: str
    kind: str = "person"  # "person" | "text"
    # person-ish structured fields
    name: str = ""
    aliases: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    attributes: dict = Field(default_factory=dict)
    # text kind
    text: str = ""
    # surveillance extras
    observed_at: str = ""
    location: str = ""
    # extra relations to project after the record lands:
    # {"target_type": "person"|"location"|"case"..., "target": str,
    #  "relation": str, "confidence": float}
    relations: list[dict] = Field(default_factory=list)


@runtime_checkable
class BaseAdapter(Protocol):
    """Contract: parse(raw) -> list[CanonicalRecord] feeding the F1/F2 pipeline."""

    source_type: str

    def parse(self, raw: Any) -> list[CanonicalRecord]: ...


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    _REGISTRY[cls.source_type] = cls
    return cls


def get_adapter(source_type: str) -> type:
    if source_type not in _REGISTRY:
        raise KeyError(source_type)
    return _REGISTRY[source_type]


def list_source_types() -> list[str]:
    return sorted(_REGISTRY)


def iter_records(adapter_cls: type, raw: Any) -> Iterator[CanonicalRecord]:
    instance = adapter_cls()
    for rec in instance.parse(raw):
        yield rec


# ---------------------------------------------------------------------------
# edge-property table (additive; OBSERVED_AT time lives here, edges schema
# untouched)
# ---------------------------------------------------------------------------
def ensure_edge_props_table() -> None:
    with get_db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS edge_props (
                   edge_id TEXT NOT NULL,
                   key TEXT NOT NULL,
                   value TEXT NOT NULL,
                   PRIMARY KEY (edge_id, key))"""
        )


def set_edge_prop(edge_id: str, key: str, value: str) -> None:
    ensure_edge_props_table()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO edge_props (edge_id, key, value) VALUES (?, ?, ?)
               ON CONFLICT(edge_id, key) DO UPDATE SET value=excluded.value""",
            (edge_id, key, value),
        )


def get_edge_props(edge_id: str) -> dict:
    ensure_edge_props_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT key, value FROM edge_props WHERE edge_id=?", (edge_id,)).fetchall()
    return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------------
# pipeline hops (shared by all adapters)
# ---------------------------------------------------------------------------
def _ingest_case_ref(case_no: str, case_id: str) -> str:
    """Prior case ids become CASE-* org nodes (idempotent)."""
    from graph_store import upsert_entity
    from models import EntityNode

    node_id = f"CASE-{case_no}"
    upsert_entity(EntityNode(id=node_id, name=case_no, aliases=[],
                             phone_numbers=[], entity_type="CASE",
                             base_risk_score=0.0), case_id)
    return node_id


def ingest_person_record(rec: CanonicalRecord, case_id: str) -> str:
    """Structured person -> ingest_canonical (resolve hop) -> node id."""
    from entity_resolution import ingest_canonical
    from graph_store import get_entities, upsert_entity

    init_db()
    attrs = dict(rec.attributes)
    attrs.setdefault("aliases", rec.aliases)
    attrs.setdefault("phones", rec.phones)
    ce = CanonicalEntity(
        id="", type="person", canonical_name=rec.name or rec.record_id,
        attributes=attrs,
        source_refs=[SourceRef(source_type=rec.source_type,
                               record_id=rec.record_id, confidence=1.0)])
    node_id = ingest_canonical(ce, case_id)["node_id"]
    if rec.aliases:
        # ingest_canonical upserts aliases=[]; union adapter aliases onto the
        # persisted row so the alias-aware blocking pass can use them.
        existing = next((e for e in get_entities(case_id) if e.id == node_id), None)
        merged = sorted(set(existing.aliases if existing else []) | set(rec.aliases))
        if existing and merged != existing.aliases:
            upsert_entity(EntityNode(id=node_id, name=existing.name,
                                     aliases=merged,
                                     phone_numbers=existing.phone_numbers,
                                     entity_type=existing.entity_type,
                                     base_risk_score=existing.base_risk_score),
                          case_id)
    return node_id


def ingest_text_record(rec: CanonicalRecord, case_id: str) -> dict:
    """Text record -> F2 pipeline verbatim (extract -> ingest -> resolve)."""
    from extraction import ingest_text

    return ingest_text(case_id, rec.source_type, rec.text, rec.record_id)


def project_relations(rec: CanonicalRecord, source_node_id: str, case_id: str) -> int:
    """Adapter-declared relations -> deterministic, idempotent graph edges."""
    from graph_store import upsert_edge
    from models import EvidenceEdge

    created = 0
    for rel in rec.relations:
        ttype, target = rel.get("target_type", "case"), str(rel.get("target", ""))
        if not target:
            continue
        if ttype == "case":
            tid = _ingest_case_ref(target, case_id)
        else:
            tid = ingest_person_record(CanonicalRecord(
                source_type=rec.source_type, record_id=f"{rec.record_id}:{target}",
                kind="person", name=target), case_id)
        relation = rel.get("relation", "ASSOCIATED_WITH")
        eid = f"{rec.source_type.upper()}:{rec.record_id}:{source_node_id}->{tid}:{relation}"
        upsert_edge(EvidenceEdge(
            source_id=source_node_id, target_id=tid, relation_type=relation,
            confidence_score=float(rel.get("confidence", STRUCT_EDGE_CONF)),
            evidence_source=f"{rec.source_type} {rec.record_id}: {relation} -> {target}"),
            case_id, link_id=eid, status="PENDING")
        created += 1
    return created


def ingest_record(rec: CanonicalRecord, case_id: str) -> dict:
    """One CanonicalRecord through the shared pipeline. Returns a stats dict."""
    if rec.kind == "text":
        out = ingest_text_record(rec, case_id)
        node_id = ""
    else:
        node_id = ingest_person_record(rec, case_id)
    rels = project_relations(rec, node_id, case_id) if node_id else 0
    return {"record_id": rec.record_id, "node_id": node_id,
            "relations": rels, "text_result": out if rec.kind == "text" else None}


def run_adapter(adapter_cls: type, raw: Any, case_id: str) -> dict:
    """normalize -> extract/ingest -> resolve -> graph for a whole payload."""
    init_db()
    results = [ingest_record(r, case_id) for r in iter_records(adapter_cls, raw)]
    from entity_resolution import resolve_case

    resolution = resolve_case(case_id)
    return {"case_id": case_id, "source_type": adapter_cls.source_type,
            "records": results, "record_count": len(results),
            "resolution": resolution}


def _coerce_records(raw: Any) -> list[dict]:
    """Accept a single dict, a list of dicts, or a JSON string of either."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict):
        return [raw]
    return [r for r in raw if isinstance(r, dict)]
