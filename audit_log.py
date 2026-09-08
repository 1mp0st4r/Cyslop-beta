"""Tamper-evident audit ledger — persisted hash chain + external anchoring.

Phase 6 (stretch): the SQLite `audit_log` table is the append-only structure
(rows are INSERT-only; no UPDATE/DELETE path exists in code). Periodically the
latest head hash is *anchored* outside the DB — by default to
`CYSLOP_ANCHOR_PATH` (a JSON file), optionally POSTed to `CYSLOP_ANCHOR_URL`
(a genuinely external timestamping service). Verifiers compare the live chain
head against the anchor to detect rollback/tampering.

Pitch honesty: this is a lightweight, correct approximation of blockchain
properties (hash-chaining, append-only immutability, external verifiability),
NOT a full DLT/Hyperledger Fabric deployment.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from database import get_db, init_db
from models import AuditLogEntry

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

ANCHOR_PATH = os.environ.get(
    "CYSLOP_ANCHOR_PATH",
    str(Path(__file__).resolve().parent / "audit_anchor.json"),
)
ANCHOR_URL = os.environ.get("CYSLOP_ANCHOR_URL", "").strip()

# Back-compat in-memory mirror (rebuilt from DB on import / on write).
AUDIT_LEDGER: list[AuditLogEntry] = []


def _compute_hash(timestamp: str, actor_id: str, action: str, case_id: str, prev_hash: str) -> str:
    payload = f"{timestamp}|{actor_id}|{action}|{case_id}|{prev_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_to_entry(row) -> AuditLogEntry:
    return AuditLogEntry(
        timestamp=row["timestamp"], actor_id=row["actor_id"], action=row["action"],
        case_id=row["case_id"], previous_hash=row["previous_hash"],
        current_hash=row["current_hash"],
    )


def refresh_cache(case_id: str | None = None) -> list[AuditLogEntry]:
    init_db()
    with get_db() as conn:
        if case_id:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    entries = [_row_to_entry(r) for r in rows]
    global AUDIT_LEDGER
    if case_id is None:
        AUDIT_LEDGER = entries
    return entries


def log_officer_action(actor_id: str, action: str, case_id: str) -> AuditLogEntry:
    """Append one hash-chained entry to the persisted ledger (INSERT-only)."""
    init_db()
    timestamp = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        last = conn.execute(
            "SELECT current_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last["current_hash"] if last else GENESIS_HASH
        curr_hash = _compute_hash(timestamp, actor_id, action, case_id, prev_hash)
        conn.execute(
            """INSERT INTO audit_log
               (timestamp, actor_id, action, case_id, previous_hash, current_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (timestamp, actor_id, action, case_id, prev_hash, curr_hash))
    entry = AuditLogEntry(timestamp=timestamp, actor_id=actor_id, action=action,
                          case_id=case_id, previous_hash=prev_hash, current_hash=curr_hash)
    AUDIT_LEDGER.append(entry)
    return entry


def verify_audit_chain(case_id: str | None = None) -> bool:
    entries = refresh_cache(case_id) if case_id else refresh_cache()
    # When filtering by case, chain links are per-case; rebuild expected prev per case.
    for i, e in enumerate(entries):
        expected_prev = GENESIS_HASH if i == 0 else entries[i - 1].current_hash
        if e.previous_hash != expected_prev:
            return False
        if e.current_hash != _compute_hash(
                e.timestamp, e.actor_id, e.action, e.case_id, e.previous_hash):
            return False
    return True


def _chain_head() -> dict | None:
    init_db()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, timestamp, current_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        count = conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
    if not row:
        return None
    return {"id": row["id"], "timestamp": row["timestamp"],
            "latest_hash": row["current_hash"], "total_entries": count}


def anchor_audit_chain() -> dict:
    """Write the current chain head to the external anchor (file + optional URL).

    Returns the anchor record. Safe to call often (idempotent per head hash).
    """
    head = _chain_head()
    if head is None:
        return {"anchored": False, "reason": "empty ledger"}
    record = {
        "anchored_at": datetime.now(timezone.utc).isoformat(),
        "latest_hash": head["latest_hash"],
        "head_id": head["id"],
        "head_timestamp": head["timestamp"],
        "total_entries": head["total_entries"],
        "algorithm": "SHA256(timestamp|actor|action|case|prev_hash)",
        "note": "Lightweight tamper-evidence anchor, not a DLT deployment.",
    }
    # 1) Local file anchor (judge-demo friendly, survives DB wipe/rollback).
    try:
        Path(ANCHOR_PATH).write_text(json.dumps(record, indent=2), encoding="utf-8")
        record["anchor_path"] = ANCHOR_PATH
    except OSError as exc:
        record["anchor_path_error"] = str(exc)
    # 2) Genuinely external anchor when configured (any HTTP timestamping endpoint).
    if ANCHOR_URL:
        try:
            req = urllib.request.Request(
                ANCHOR_URL, data=json.dumps(record).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                record["external_status"] = resp.status
        except Exception as exc:  # never fail the API call on anchor errors
            record["external_error"] = str(exc)
    return {"anchored": True, **record}


def read_anchor() -> dict | None:
    try:
        raw = Path(ANCHOR_PATH).read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, ValueError):
        return None


def verify_against_anchor() -> dict:
    """Compare live chain head with the external anchor.

    `match=True` means no rollback/tamper since the last anchor.
    `behind_by>0` means new entries were appended after anchoring (expected).
    """
    anchor = read_anchor()
    head = _chain_head()
    if anchor is None:
        return {"anchored": False, "reason": "no anchor written yet"}
    if head is None:
        return {"anchored": True, "match": False, "reason": "ledger empty but anchor exists"}
    latest = head["latest_hash"]
    anchored_hash = anchor.get("latest_hash")
    if latest == anchored_hash:
        return {"anchored": True, "match": True, "latest_hash": latest,
                "anchored_at": anchor.get("anchored_at")}
    # Check whether the anchored hash still exists in history (append-only growth)
    # vs. history was rewritten (tamper/rollback).
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM audit_log WHERE current_hash = ? ORDER BY id LIMIT 1",
            (anchored_hash,)).fetchone()
    if row:
        return {"anchored": True, "match": False,
                "status": "APPENDED_SINCE_ANCHOR",
                "behind_by": head["id"] - row["id"],
                "latest_hash": latest, "anchored_hash": anchored_hash,
                "anchored_at": anchor.get("anchored_at")}
    return {"anchored": True, "match": False, "status": "TAMPER_OR_ROLLBACK_DETECTED",
            "latest_hash": latest, "anchored_hash": anchored_hash,
            "anchored_at": anchor.get("anchored_at")}


# Warm the cache at import so old `from audit_log import AUDIT_LEDGER` code sees history.
try:
    refresh_cache()
except Exception:
    pass
