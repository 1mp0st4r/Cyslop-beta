"""Surveillance report adapter — unstructured text.

Reuses the F2 extraction pipeline verbatim (``extraction.ingest_text`` with
``source_type="surveillance_report"``), then adds the adapter-specific hop:
a parseable ``observed_at`` timestamp + location mention produce an
OBSERVED_AT edge (person -> location) carrying the time property in the
additive ``edge_props`` table. A known phone in the text still yields the
standard USES edges from F2 relation derivation.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .base import (OBSERVED_EDGE_CONF, CanonicalRecord, get_edge_props, register,
                   set_edge_prop)

# header forms the fixture writer controls; free text still flows through F2
OBSERVED_AT_RE = re.compile(
    r"observed_at\s*[:=]\s*(.+)", re.IGNORECASE)
LOCATION_HEADER_RE = re.compile(r"location\s*[:=]\s*(.+)", re.IGNORECASE)
TS_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


@register
class SurveillanceReportAdapter:
    source_type = "surveillance_report"

    def parse(self, raw: Any) -> list[CanonicalRecord]:
        rows = self._rows(raw)
        return [self._record(r) for r in rows]

    def _rows(self, raw: Any) -> list[dict]:
        if isinstance(raw, str):
            return [{"text": raw}]
        if isinstance(raw, dict):
            return [raw]
        return [r for r in raw if isinstance(r, dict)]

    def _record(self, row: dict) -> CanonicalRecord:
        text = row.get("text") or row.get("summary") or ""
        observed_at = str(row.get("observed_at") or "").strip()
        if not observed_at:
            m = OBSERVED_AT_RE.search(text)
            if m:
                observed_at = m.group(1).strip()
        location = str(row.get("location") or "").strip()
        if not location:
            m = LOCATION_HEADER_RE.search(text)
            if m:
                location = m.group(1).strip()
        return CanonicalRecord(
            source_type=self.source_type,
            record_id=str(row.get("record_id") or row.get("report_id") or ""),
            kind="text", text=text,
            observed_at=observed_at, location=location)


def add_observed_at(case_id: str, record_id: str, person_node: str,
                    location_node: str, observed_at: str) -> str:
    """OBSERVED_AT edge + time property. Deterministic id -> idempotent."""
    from graph_store import upsert_edge
    from models import EvidenceEdge

    eid = f"OBSERVED_AT:{record_id}:{person_node}->{location_node}"
    ts = _normalize_ts(observed_at)
    upsert_edge(EvidenceEdge(
        source_id=person_node, target_id=location_node,
        relation_type="OBSERVED_AT", confidence_score=OBSERVED_EDGE_CONF,
        evidence_source=f"surveillance_report {record_id}: observed at {ts}"),
        case_id, link_id=eid, status="PENDING")
    set_edge_prop(eid, "observed_at", ts)
    return eid


def _normalize_ts(raw: str) -> str:
    raw = (raw or "").strip()
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(
                tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return raw  # store as-given if unparseable; never fail ingestion


def observed_at_of(edge_id: str) -> str:
    return get_edge_props(edge_id).get("observed_at", "")
