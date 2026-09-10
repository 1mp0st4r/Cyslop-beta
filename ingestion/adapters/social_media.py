"""Social media intelligence adapter — MOCK (JSON fixture).

Fixture schema:
    {"account_handle": "...", "platform": "...", "author_name": "...",
     "mentions": ["...", ...], "timestamps": ["...", ...]}

mentions -> COMMUNICATES_WITH edges (author -> mentioned).

MOCK STATUS: this adapter reads a canned JSON fixture shape, not a live API.
Real-API extension point: replace ``parse`` with a platform client call that
returns the same ``CanonicalRecord`` objects (account_handle -> name,
mentions -> relations); nothing else in the pipeline changes.
"""
from __future__ import annotations

import json
from typing import Any

from .base import (COMMUNICATES_CONF, CanonicalRecord, register)


@register
class SocialMediaAdapter:
    source_type = "social_media"  # mock adapter — see module docstring

    def parse(self, raw: Any) -> list[CanonicalRecord]:
        rows = self._rows(raw)
        return [self._record(r, i) for i, r in enumerate(rows)]

    def _rows(self, raw: Any) -> list[dict]:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict):
            return [raw]
        return [r for r in raw if isinstance(r, dict)]

    def _record(self, row: dict, idx: int) -> CanonicalRecord:
        author = (row.get("author_name")
                  or row.get("account_handle") or f"SM-{idx + 1}").strip()
        mentions = [m if isinstance(m, str) else str(m.get("name") or m.get("handle") or "")
                    for m in (row.get("mentions") or [])]
        mentions = [m.strip() for m in mentions if m and m.strip()]
        rid = str(row.get("record_id") or row.get("account_handle") or f"SM-{idx + 1}")
        return CanonicalRecord(
            source_type=self.source_type, record_id=rid, kind="person",
            name=author,
            attributes={"account_handle": row.get("account_handle", ""),
                        "platform": row.get("platform", ""),
                        "timestamps": row.get("timestamps", [])},
            relations=[{"target_type": "person", "target": m,
                        "relation": "COMMUNICATES_WITH",
                        "confidence": COMMUNICATES_CONF} for m in mentions])
