"""Intelligence agency report adapter — MOCK (text fixture).

Reuses the F2 text pipeline verbatim with ``source_type="agency_report"``:
text -> extraction.extract -> CanonicalEntity(SourceRef w/ span) ->
entity_resolution.resolve_case -> graph upsert, idempotent via
extraction_runs content-hash dedupe.

MOCK STATUS: fixtures are canned text blobs. Real-API extension point:
swap the fixture loader for an agency feed client that yields the same
{"record_id", "text"} dicts; zero pipeline changes required.
"""
from __future__ import annotations

from typing import Any

from .base import CanonicalRecord, register


@register
class AgencyReportAdapter:
    source_type = "agency_report"  # mock adapter — see module docstring

    def parse(self, raw: Any) -> list[CanonicalRecord]:
        rows = self._rows(raw)
        return [self._record(r, i) for i, r in enumerate(rows)]

    def _rows(self, raw: Any) -> list[dict]:
        if isinstance(raw, str):
            return [{"text": raw}]
        if isinstance(raw, dict):
            return [raw]
        return [r for r in raw if isinstance(r, dict)]

    def _record(self, row: dict, idx: int) -> CanonicalRecord:
        text = row.get("text") or row.get("summary") or ""
        return CanonicalRecord(
            source_type=self.source_type,
            record_id=str(row.get("record_id") or row.get("report_id") or f"AGY-{idx + 1}"),
            kind="text", text=text)
