"""F2 Unstructured Text Extraction Pipeline — regex + pluggable spaCy NER.

Composes three extractors:
  1. Deterministic regex (phones, vehicles, amounts) — high precision.
  2. spaCy NER via pluggable NerBackend (PERSON/ORG/GPE/LOC).
  3. Name normalization reused from entity_resolution (no reimplementation).

Output: list[Extraction] with char spans -> CanonicalEntity(SourceRef w/ span)
-> resolver.run (entity_resolution.resolve_case) -> graph upsert.
Idempotent via extraction_runs keyed by (source_type, record_id, content_hash).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from database import ensure_entity_sources_table, get_db, init_db
from models import ENTITY_TYPES, CanonicalEntity, SourceRef

PHONE_RE = re.compile(r"(?:\+?91[\s\-]?)?[6-9]\d{4}[\s\-]?\d{5}")
VEHICLE_RE = re.compile(r"\b[A-Z]{2}[\s\-]?\d{1,2}[\s\-]?[A-Z]{1,3}[\s\-]?\d{3,4}\b")
AMOUNT_RE = re.compile(r"(?:₹\s?[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?\s?(?:lakh|crore|L|Cr))")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")
PERSON_VEHICLE_TRIGGERS = re.compile(
    r"\b(driving|riding|driver|rider|vehicle(?:\s*no\.?)?|registration(?:\s*no\.?)?|plate(?:\s*no\.?)?|owned\s+by|belonging\s+to)\b",
    re.IGNORECASE,
)


class Extraction(BaseModel):
    entity_type: Literal["person", "phone", "vehicle", "location", "organization"]
    text: str
    span_start: int
    span_end: int
    confidence: float = Field(ge=0.0, le=1.0)


class NerBackend(Protocol):
    def entities(self, text: str) -> list[Extraction]: ...


class SpacyNerBackend:
    """English spaCy backend. Model picked at construction; largest clean install wins."""

    def __init__(self, model: str = "en_core_web_sm"):
        self.model = model
        self._nlp = None

    def _load(self):
        if self._nlp is not None:
            return self._nlp
        try:
            import spacy
            try:
                self._nlp = spacy.load(self.model)
            except OSError:
                self._nlp = spacy.blank("en")
                if "sentencizer" not in self._nlp.pipe_names:
                    self._nlp.add_pipe("sentencizer")
            return self._nlp
        except ImportError:
            return None

    def entities(self, text: str) -> list[Extraction]:
        nlp = self._load()
        if nlp is None or not nlp.has_pipe("ner"):
            return []
        out: list[Extraction] = []
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                out.append(Extraction(entity_type="person", text=ent.text.strip(),
                                     span_start=ent.start_char, span_end=ent.end_char,
                                     confidence=0.85))
            elif ent.label_ == "ORG":
                out.append(Extraction(entity_type="organization", text=ent.text.strip(),
                                     span_start=ent.start_char, span_end=ent.end_char,
                                     confidence=0.80))
            elif ent.label_ in ("GPE", "LOC"):
                out.append(Extraction(entity_type="location", text=ent.text.strip(),
                                     span_start=ent.start_char, span_end=ent.end_char,
                                     confidence=0.80))
        return out


class RegexFallbackNer:
    """Offline fallback: capitalized multi-word spans as person candidates."""

    _RE = re.compile(r"\b(?:[A-Z]\.\s*)?[A-Z][a-z]+\s+[A-Z][a-z]+\b")

    def entities(self, text: str) -> list[Extraction]:
        return [Extraction(entity_type="person", text=m.group(0).strip(),
                           span_start=m.start(), span_end=m.end(), confidence=0.55)
                for m in self._RE.finditer(text)]


def extract_regex(text: str) -> list[Extraction]:
    out: list[Extraction] = []
    for m in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) != 10 or digits[0] not in "6789":
            continue
        out.append(Extraction(entity_type="phone", text=m.group(0),
                             span_start=m.start(), span_end=m.end(), confidence=0.98))
    for m in VEHICLE_RE.finditer(text):
        out.append(Extraction(entity_type="vehicle", text=m.group(0),
                             span_start=m.start(), span_end=m.end(), confidence=0.97))
    return out


def extract(text: str, backend: NerBackend | None = None) -> list[Extraction]:
    """Compose regex + NER extractors; dedupe by (type, span)."""
    found = extract_regex(text)
    be = backend or SpacyNerBackend()
    ner = be.entities(text)
    if not any(e.entity_type == "person" for e in ner):
        ner = ner + RegexFallbackNer().entities(text)
    seen = {(e.entity_type, e.span_start, e.span_end) for e in found}
    for e in ner:
        if (e.entity_type, e.span_start, e.span_end) not in seen:
            found.append(e)
            seen.add((e.entity_type, e.span_start, e.span_end))
    return sorted(found, key=lambda e: e.span_start)


def sentences(text: str) -> list[tuple[str, int, int]]:
    """Return (sentence, start, end) spans for relation evidence."""
    out, pos = [], 0
    for part in SENT_SPLIT_RE.split(text):
        if not part.strip():
            continue
        s = text.find(part, pos)
        if s < 0:
            s = pos
        e = s + len(part)
        out.append((part, s, e))
        pos = e
    return out or [(text, 0, len(text))]


def derive_relations(text: str, extractions: list[Extraction]) -> list[dict]:
    """Same-sentence co-occurrence -> ASSOCIATED_WITH; person-phone/vehicle -> USES."""
    rels: list[dict] = []
    for sent, ss, se in sentences(text):
        inside = [e for e in extractions if e.span_start >= ss and e.span_end <= se]
        persons = [e for e in inside if e.entity_type == "person"]
        others = [e for e in inside if e.entity_type != "person"]
        for i in range(len(inside)):
            for j in range(i + 1, len(inside)):
                rels.append({"a_text": inside[i].text, "a_type": inside[i].entity_type,
                             "b_text": inside[j].text, "b_type": inside[j].entity_type,
                             "relation": "ASSOCIATED_WITH",
                             "evidence": sent.strip()[:280], "span": [ss, se],
                             "confidence": 0.6})
        targets = [e for e in inside if e.entity_type in ("phone", "vehicle")]
        if targets and (persons or PERSON_VEHICLE_TRIGGERS.search(sent)):
            for p in persons or inside:
                for t in targets:
                    if p is t:
                        continue
                    rels.append({"a_text": p.text, "a_type": p.entity_type,
                                 "b_text": t.text, "b_type": t.entity_type,
                                 "relation": "USES",
                                 "evidence": sent.strip()[:280], "span": [ss, se],
                                 "confidence": 0.75})
    # dedupe
    seen, uniq = set(), []
    for r in rels:
        k = (r["a_text"], r["b_text"], r["relation"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def _run_key(source_type: str, record_id: str, content_hash: str) -> str:
    return f"{source_type}:{record_id}:{content_hash}"


def ingest_text(case_id: str, source_type: str, text: str,
                record_id: str = "", backend: NerBackend | None = None) -> dict:
    """text -> extract() -> CanonicalEntities(SourceRef w/ spans) -> resolver.run()."""
    from entity_resolution import ingest_canonical, resolve_case
    from graph_store import upsert_edge
    from models import EvidenceEdge

    init_db()
    ensure_entity_sources_table()
    content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    rid = record_id or f"TEXT-{content_hash}"
    key = _run_key(source_type, rid, content_hash)
    with get_db() as conn:
        row = conn.execute("SELECT result FROM extraction_runs WHERE run_key=?", (key,)).fetchone()
        if row is not None:
            cached = json.loads(row["result"] or "{}")
            cached["deduped"] = True
            return cached
    exts = extract(text, backend)
    created, merged_summaries = 0, []
    text_to_node: dict[tuple[str, str], str] = {}
    for e in exts:
        ce = CanonicalEntity(id="", type=e.entity_type, canonical_name=e.text,
                             attributes={}, source_refs=[SourceRef(
                                 source_type=source_type, record_id=rid,
                                 span=[e.span_start, e.span_end], confidence=e.confidence)])
        res = ingest_canonical(ce, case_id)
        text_to_node[(e.entity_type, e.text)] = res["node_id"]
        created += 1
    # persist spans per node (every entity from this path carries span)
    with get_db() as conn:
        for e in exts:
            nid = text_to_node.get((e.entity_type, e.text), "")
            if nid:
                conn.execute(
                    """INSERT INTO entity_sources
                       (entity_id, case_id, source_type, record_id, span_start, span_end, confidence)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (nid, case_id, source_type, rid, e.span_start, e.span_end, e.confidence))
    rels = derive_relations(text, exts)
    rel_created = 0
    for r in rels:
        a = text_to_node.get((r["a_type"], r["a_text"]))
        b = text_to_node.get((r["b_type"], r["b_text"]))
        if not a or not b or a == b:
            continue
        eid = f"TEXT:{rid}:{a}->{b}:{r['relation']}"
        try:
            upsert_edge(EvidenceEdge(source_id=a, target_id=b, relation_type=r["relation"],
                                     confidence_score=r["confidence"],
                                     evidence_source=f"{source_type} {rid}: {r['evidence']}"),
                        case_id, link_id=eid,
                        status="CONFIRMED" if r["relation"] == "USES" else "PENDING")
            rel_created += 1
        except Exception:
            continue
    resolve_out = resolve_case(case_id)
    result = {"case_id": case_id, "record_id": rid, "content_hash": content_hash,
              "entities_created": created,
              "entities_merged": resolve_out.get("auto_merge_count", 0),
              "relations_created": rel_created,
              "resolve": resolve_out, "deduped": False}
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO extraction_runs
               (run_key, case_id, source_type, record_id, content_hash, created_at, result)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key, case_id, source_type, rid, content_hash,
             datetime.now(timezone.utc).isoformat(), json.dumps(result)))
    return result
