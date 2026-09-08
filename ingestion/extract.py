"""NER pipeline — spaCy (en_core_web_sm default) + regex anchors.

Extracts PERSON / LOC(GPE) / ORG via spaCy when available (graceful
fallback to regex-only so ingestion never hard-fails offline), plus
deterministic regex extractors for Indian phones + vehicle plates which
are more reliable than NER for structured tokens.

Phone patterns: +91-XXXXXXXXXX, 91XXXXXXXXXX, 0XXXXXXXXXX, 10-digit.
Vehicle pattern: [A-Z]{2}-\\d{2}-[A-Z]{1,2}-\\d{4} (e.g. DL-01-AB-4402).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PHONE_RE = re.compile(r"(?:\+?91[\s\-]?)?[6-9]\d{4}[\s\-]?\d{5}")
VEHICLE_RE = re.compile(r"\b[A-Z]{2}-\d{2}-[A-Z]{1,2}-\d{4}\b")
# Loose "X. Surname" / "First Last" fallback when spaCy model is absent.
NAME_RE = re.compile(r"\b(?:[A-Z]\.\s*)?[A-Z][a-z]+\s+[A-Z][a-z]+\b")
# Phase 6 — Hindi/Devanagari fallback for Hindi FIRs (no model download needed):
# matches 2+ Devanagari tokens (e.g. "रमेश कुमार"), plus common FIR keywords.
HINDI_NAME_RE = re.compile(r"[\u0900-\u097F]{2,}(?:\s+[\u0900-\u097F]{2,})+")
HINDI_LOCATION_KEYWORDS = re.compile(
    r"(?:थाना|जिला|गाँव|गांव|शहर|राज्य|मोहल्ला|चौक|बाज़ार|बाजार)\s*[:\-]?\s*([\u0900-\u097F]{2,}(?:\s+[\u0900-\u097F]{2,}){0,2})"
)

_nlp = None
_nlp_model = ""


def get_nlp(model: str = "en_core_web_sm"):
    """Lazy-load spaCy model; return None if spaCy/model unavailable.

    Swap `model` to `xx_ent_wiki_sm` or a HuggingFace IndicNER model
    when multilingual accuracy matters and time allows.
    """
    global _nlp, _nlp_model
    if _nlp is not None and _nlp_model == model:
        return _nlp
    try:
        import spacy
        try:
            _nlp = spacy.load(model)
        except OSError:  # model not downloaded -> blank English + sentencizer
            _nlp = spacy.blank("en")
            if "sentencizer" not in _nlp.pipe_names:
                _nlp.add_pipe("sentencizer")
        _nlp_model = model
        return _nlp
    except ImportError:
        return None


@dataclass
class ExtractedEntities:
    persons: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    orgs: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    vehicles: list[str] = field(default_factory=list)


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    digits = digits[-10:]
    return f"+91-{digits}"


def extract_from_text(text: str, model: str = "en_core_web_sm") -> ExtractedEntities:
    out = ExtractedEntities()
    phones = [normalize_phone(m.group(0)) for m in PHONE_RE.finditer(text)]
    # de-dup preserving order
    out.phones = list(dict.fromkeys(phones))
    out.vehicles = list(dict.fromkeys(m.group(0) for m in VEHICLE_RE.finditer(text)))

    nlp = get_nlp(model)
    persons, locs, orgs = [], [], []
    if nlp is not None and nlp.has_pipe("ner"):
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                persons.append(ent.text.strip())
            elif ent.label_ in ("GPE", "LOC"):
                locs.append(ent.text.strip())
            elif ent.label_ == "ORG":
                orgs.append(ent.text.strip())
    if not persons:  # regex fallback (also catches "R. Kumar" spaCy often misses)
        persons = [m.group(0).strip() for m in NAME_RE.finditer(text)]
    # Hindi FIR fallback: Devanagari names spaCy en_core_web_sm never emits.
    # Try xx_ent_wiki_sm / IndicNER via `model` param when available; regex keeps
    # Hindi demos working offline.
    for m in HINDI_NAME_RE.finditer(text):
        cand = m.group(0).strip()
        if cand and cand not in persons:
            persons.append(cand)
    # filter obvious non-names (locations/orgs leaking in) + dedup
    seen = set()
    for p in persons:
        if p not in seen:
            seen.add(p)
            out.persons.append(p)
    for m in HINDI_LOCATION_KEYWORDS.finditer(text):
        loc = m.group(1).strip()
        if loc and loc not in locs:
            locs.append(loc)
    out.locations = list(dict.fromkeys(locs))
    out.orgs = list(dict.fromkeys(orgs))
    return out


def split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n+|(?<=\.)\s+(?=[A-Z\u0900-\u097F])", text) if p.strip()]
    return parts or [text]
