"""Entity resolution — anchor + fuzzy name matching (rapidfuzz).

Rules:
- Same normalized phone or same vehicle plate  -> auto-merge (conf 0.95).
- Else rapidfuzz token_set_ratio on names:
    >= AUTO_MERGE (90) + shared context (phone/vehicle/loc/org overlap)
        -> auto-merge; score = fuzz/100 scaled.
    >= REVIEW_THRESHOLD (75) -> flag PENDING_REVIEW (human-in-the-loop).
    below -> distinct entity.
Falls back to difflib when rapidfuzz is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

AUTO_MERGE = 90
REVIEW_THRESHOLD = 75

try:
    from rapidfuzz import fuzz as _fuzz

    def name_sim(a: str, b: str) -> float:
        return float(_fuzz.token_set_ratio(a, b))
except ImportError:  # pragma: no cover
    import difflib

    def name_sim(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100


@dataclass
class CanonicalEntity:
    key: str  # node id e.g. ENT-0001
    name: str
    aliases: list[str] = field(default_factory=list)
    phones: set[str] = field(default_factory=set)
    vehicles: set[str] = field(default_factory=set)
    contexts: set[str] = field(default_factory=set)  # locs+orgs+fir_nos
    entity_type: str = "PERSON"


@dataclass
class Resolution:
    canonical: CanonicalEntity
    confidence: float
    needs_review: bool
    matched_alias: str = ""


class EntityResolver:
    def __init__(self, auto_merge: int = AUTO_MERGE, review: int = REVIEW_THRESHOLD):
        self.auto_merge = auto_merge
        self.review = review
        self.canonicals: list[CanonicalEntity] = []
        self.pending_review: list[dict] = []
        self._counter = 0

    def _new(self, name: str, phones, vehicles, contexts, etype="PERSON") -> CanonicalEntity:
        self._counter += 1
        c = CanonicalEntity(key=f"ENT-{self._counter:04d}", name=name,
                            phones=set(phones or []), vehicles=set(vehicles or []),
                            contexts=set(contexts or []), entity_type=etype)
        self.canonicals.append(c)
        return c

    def resolve(self, name: str, phones=(), vehicles=(), contexts=(),
                entity_type: str = "PERSON") -> Resolution:
        phones, vehicles, contexts = set(phones or []), set(vehicles or []), set(contexts or [])
        # 1. hard-anchor merge
        for c in self.canonicals:
            if c.entity_type != entity_type:
                continue
            if phones & c.phones or (vehicles & c.vehicles and entity_type == "PERSON"):
                conf = 0.95
                self._merge(c, name, phones, vehicles, contexts)
                return Resolution(c, conf, False, name)
        # 2. fuzzy name merge
        best, best_score = None, 0.0
        for c in self.canonicals:
            if c.entity_type != entity_type:
                continue
            s = max(name_sim(name, cand) for cand in [c.name, *c.aliases])
            if s > best_score:
                best, best_score = c, s
        if best is not None:
            shared = bool((phones & best.phones) or (vehicles & best.vehicles) or (contexts & best.contexts))
            if best_score >= self.auto_merge and (shared or best_score >= 96):
                conf = round(0.70 + (best_score / 100) * 0.28, 3)
                self._merge(best, name, phones, vehicles, contexts)
                return Resolution(best, conf, False, name)
            if best_score >= self.review:
                self.pending_review.append({"mention": name, "candidate": best.name,
                                            "candidate_key": best.key, "score": round(best_score, 1),
                                            "status": "PENDING_REVIEW"})
                # do NOT merge — create distinct node pending human decision
                c = self._new(name, phones, vehicles, contexts, entity_type)
                return Resolution(c, round(best_score / 100 * 0.6, 3), True, name)
        c = self._new(name, phones, vehicles, contexts, entity_type)
        return Resolution(c, 0.85 if phones or vehicles else 0.65, False, name)

    def _merge(self, c: CanonicalEntity, name, phones, vehicles, contexts):
        if name != c.name and name not in c.aliases:
            c.aliases.append(name)
        c.phones |= phones
        c.vehicles |= vehicles
        c.contexts |= contexts
