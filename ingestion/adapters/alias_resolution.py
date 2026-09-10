"""F5 additive alias-aware resolution pass (entity_resolution.py untouched).

The criminal-history adapter stores aliases as entity alias attributes. This
pass re-runs the F1 pairwise logic over the same PERSON rows but treats every
alias as an additional name candidate when blocking (R1/R5 blocking keys) and
when scoring similarity — so a shared phone + a strong alias match can auto-
merge where primary names alone would have scored < 85.

Rules (same semantics as F1, additive rule id):
- shared phone + best-candidate sim >= 85  -> auto merge, rule ``exact_anchor+name_alias``
- best-candidate sim >= 95, no phone       -> queued for review (R5 semantics,
  name-only never auto-merges)
Everything goes through entity_resolution.merge_entities / queue_review, so
merge logs, unmerge snapshots and idempotency behave identically. Re-running
is a no-op (deterministic merge ids).
"""
from __future__ import annotations

import json

from database import get_db, init_db
from entity_resolution import (merge_entities, name_similarity, normalize_phone,
                               queue_review)
from models import CanonicalEntity  # noqa: F401  (typing parity with F1)


def _name_tokens(name: str) -> list[str]:
    from entity_resolution import normalize_name

    return [t for t in normalize_name(name).split() if t]


def _candidates(row: dict) -> list[str]:
    return [row.get("name", ""), *json.loads(row.get("aliases") or "[]")]


def alias_block_keys(row: dict) -> set[str]:
    """R1/R5 blocking keys extended with alias tokens (additive)."""
    keys: set[str] = set()
    for p in json.loads(row.get("phone_numbers") or "[]"):
        d = normalize_phone(p)
        if d:
            keys.add(f"ph:{d}")
    for cand in _candidates(row):
        for tok in _name_tokens(cand):
            keys.add(f"nm:{tok}")
    return keys


def pair_similarity(a: dict, b: dict) -> float:
    return max((name_similarity(x, y) for x in _candidates(a) for y in _candidates(b)),
               default=0.0)


def alias_aware_resolve(case_id: str) -> dict:
    """One idempotent pass over PERSON entities in a case."""
    init_db()
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM entities WHERE case_id=? ORDER BY id", (case_id,)).fetchall()]
    persons = [r for r in rows if str(r.get("entity_type", "")).upper() == "PERSON"]
    blocks: dict[str, list[dict]] = {}
    for r in persons:
        for k in alias_block_keys(r):
            blocks.setdefault(k, []).append(r)
    merged: list[str] = []
    queued: list[str] = []
    seen: set[tuple[str, str]] = set()
    for members in blocks.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                pair = tuple(sorted([a["id"], b["id"]]))
                if pair in seen:
                    continue
                seen.add(pair)
                if a["id"] == b["id"]:
                    continue
                ph_a = {normalize_phone(p)
                        for p in json.loads(a["phone_numbers"] or "[]")} - {""}
                ph_b = {normalize_phone(p)
                        for p in json.loads(b["phone_numbers"] or "[]")} - {""}
                sim = pair_similarity(a, b)
                ev = [{"a": a["id"], "b": b["id"], "a_name": a["name"],
                       "b_name": b["name"],
                       "a_aliases": json.loads(a["aliases"] or "[]"),
                       "b_aliases": json.loads(b["aliases"] or "[]"),
                       "sim": round(sim, 1)}]
                if (ph_a & ph_b) and sim >= 85:
                    survivor = sorted([a["id"], b["id"]])[0]
                    loser = b["id"] if survivor == a["id"] else a["id"]
                    merged.append(merge_entities(
                        survivor, [loser], "exact_anchor+name_alias", 0.95, ev))
                elif sim >= 95:
                    queued.append(queue_review(
                        a["id"], b["id"], "review_candidate", sim, ev))
    return {"case_id": case_id, "alias_auto_merges": merged,
            "alias_auto_merge_count": len(merged), "alias_queued": queued,
            "alias_queued_count": len(queued)}
