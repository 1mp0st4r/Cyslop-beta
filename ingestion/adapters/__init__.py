"""F5 adapter registry + dispatch.

``dispatch_source(source_type, raw, case_id)`` routes any registered source
through the shared normalize -> extract (if text) -> resolve -> graph path.
Surveillance reports additionally post-process an OBSERVED_AT edge with a
time property (person -> location).
"""
from __future__ import annotations

from typing import Any

from .base import (CanonicalRecord, get_adapter, ingest_person_record,
                   ingest_record, iter_records, list_source_types, register,
                   run_adapter)
from . import criminal_history  # noqa: F401  (registers)
from . import social_media  # noqa: F401  (registers)
from . import surveillance  # noqa: F401  (registers)
from . import agency_report  # noqa: F401  (registers)


def _ensure_case_row(case_id: str) -> None:
    """FK guard: entities/edges reference cases(id); create the case if absent."""
    from datetime import datetime, timezone

    from database import get_db, init_db

    init_db()
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO cases (id, title, description, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (case_id, "Adapter-ingested case", "F5 adapters", "OPEN",
             datetime.now(timezone.utc).isoformat()))


def _location_node(name: str, case_id: str, source_type: str, rid: str) -> str:
    from entity_resolution import ingest_canonical
    from models import CanonicalEntity, SourceRef

    return ingest_canonical(CanonicalEntity(
        id="", type="location", canonical_name=name, attributes={},
        source_refs=[SourceRef(source_type=source_type, record_id=rid,
                               confidence=0.9)]), case_id)["node_id"]


def _surveillance_post(rec: CanonicalRecord, case_id: str, text_result: dict) -> dict:
    """OBSERVED_AT hop: person + location nodes -> edge with time property."""
    from extraction import extract
    from entity_resolution import ingest_canonical
    from models import CanonicalEntity, SourceRef

    from .surveillance import add_observed_at

    if not rec.location or not rec.observed_at:
        return {}
    persons = [e for e in extract(rec.text) if e.entity_type == "person"]
    if not persons:
        return {}
    person_node = ingest_canonical(CanonicalEntity(
        id="", type="person", canonical_name=persons[0].text, attributes={},
        source_refs=[SourceRef(source_type=rec.source_type,
                               record_id=text_result.get("record_id", rec.record_id),
                               confidence=persons[0].confidence)]), case_id)["node_id"]
    loc_node = _location_node(rec.location, case_id, rec.source_type,
                              text_result.get("record_id", rec.record_id))
    eid = add_observed_at(case_id, text_result.get("record_id", rec.record_id),
                          person_node, loc_node, rec.observed_at)
    return {"observed_at_edge": eid, "location_node": loc_node,
            "person_node": person_node}


def dispatch_source(source_type: str, raw: Any, case_id: str) -> dict:
    """One API surface: POST /ingest/{source_type} -> here."""
    adapter_cls = get_adapter(source_type)  # raises KeyError if unknown
    _ensure_case_row(case_id)
    if adapter_cls.source_type == "surveillance_report":
        from entity_resolution import resolve_case

        results = []
        for rec in iter_records(adapter_cls, raw):
            out = ingest_record(rec, case_id)
            out["observed"] = _surveillance_post(rec, case_id,
                                                 out.get("text_result") or {})
            results.append(out)
        return {"case_id": case_id, "source_type": source_type,
                "records": results, "record_count": len(results),
                "resolution": resolve_case(case_id)}
    return run_adapter(adapter_cls, raw, case_id)


def ingest_all_fixtures(case_id: str, fixtures_dir: str | None = None) -> dict:
    """Full 7-source pipeline demo: FIRs + CDRs + bank txns (F1/F2 fixtures)
    plus the four F5 adapters, then one resolution pass. Returns summary."""
    import json
    from pathlib import Path

    from ingestion.build_graph import ingest_synthetic_dir

    root = Path(fixtures_dir or Path(__file__).resolve().parents[2] / "fixtures")
    summary: dict = {"case_id": case_id, "sources": {}}
    summary["sources"]["fir_cdr_txn"] = ingest_synthetic_dir(
        root / "synthetic", case_id)
    for st, fname, kind in (
            ("criminal_history", "criminal_history.csv", "csv"),
            ("surveillance_report", "surveillance_reports.json", "json"),
            ("social_media", "social_media.json", "json"),
            ("agency_report", "agency_reports.json", "json")):
        p = root / "adapters" / fname
        if not p.exists():
            summary["sources"][st] = {"error": "fixture missing"}
            continue
        raw: Any = p.read_text(encoding="utf-8") if kind == "csv" \
            else json.loads(p.read_text(encoding="utf-8"))
        summary["sources"][st] = dispatch_source(st, raw, case_id)
    from analytics import recompute_base_risk_scores

    try:
        summary["computed_base_risk"] = recompute_base_risk_scores(case_id)
    except Exception as exc:  # never fail the demo on analytics
        summary["computed_base_risk_error"] = str(exc)
    return summary


__all__ = [
    "BaseAdapter", "CanonicalRecord", "dispatch_source", "get_adapter",
    "ingest_all_fixtures", "ingest_person_record", "ingest_record",
    "iter_records", "list_source_types", "register", "run_adapter",
]
