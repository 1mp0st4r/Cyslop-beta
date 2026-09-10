"""Criminal history DB adapter — structured CSV rows.

Columns: name, aliases (| or ; separated), phone, address, prior_case_ids
(| or ; separated). Aliases land as multiple alias attributes on the person
(the resolver treats them as additional name candidates — additive extension
to R1/R5 blocking keys). Prior cases -> ASSOCIATED_WITH edges to CASE-* nodes.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from models import CanonicalEntity, SourceRef

from .base import ASSOC_CASE_CONF, CanonicalRecord, ingest_person_record, project_relations, register


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    for sep in ("|", ";"):
        value = value.replace(sep, ",")
    return [v.strip() for v in value.split(",") if v.strip()]


@register
class CriminalHistoryAdapter:
    source_type = "criminal_history"

    def parse(self, raw: Any) -> list[CanonicalRecord]:
        rows = self._rows(raw)
        return [self._record(r, i) for i, r in enumerate(rows)]

    def _rows(self, raw: Any) -> list[dict]:
        if isinstance(raw, str):
            return list(csv.DictReader(io.StringIO(raw)))
        if isinstance(raw, dict):
            return [raw]
        return [r for r in raw if isinstance(r, dict)]

    def _record(self, row: dict, idx: int) -> CanonicalRecord:
        rid = row.get("record_id") or row.get("id") or f"CH-{idx + 1}"
        return CanonicalRecord(
            source_type=self.source_type,
            record_id=str(rid),
            kind="person",
            name=(row.get("name") or "").strip(),
            aliases=_split(row.get("aliases")),
            phones=[p for p in (_split(row.get("phone")) or []) if p],
            attributes={"address": (row.get("address") or "").strip()},
            relations=[{"target_type": "case", "target": c,
                        "relation": "ASSOCIATED_WITH", "confidence": ASSOC_CASE_CONF}
                       for c in _split(row.get("prior_case_ids"))],
        )

    # direct hop (used by tests / demo): person + prior-case edges
    def ingest_row(self, row: dict, case_id: str) -> str:
        rec = self._record(row, 0)
        node = ingest_person_record(rec, case_id)
        project_relations(rec, node, case_id)
        return node
