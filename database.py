"""Persistence layer — Phase 1: SQLite + NetworkX (in-process graph).

Schema (real tables, survives restart):
  cases(id PK, title, description, status, created_at)
  entities(id PK, case_id FK, name, aliases JSON, phone_numbers JSON,
           entity_type, base_risk_score)
  edges(id PK = link_id, case_id FK, source_id FK, target_id FK,
        relation_type, confidence_score, evidence_source, status,
        reviewer, reviewed_at)
  evidence_sources(id PK AUTOINCREMENT, edge_id FK, source_type,
                   reference, details, created_at)
  audit_log(id PK AUTOINCREMENT, timestamp, actor_id, action, case_id,
            previous_hash, current_hash)

Chosen approach: NetworkX (pure Python, zero infra) for PageRank /
betweenness / cycle detection + SQLite rows for entities/evidence/audit.
See [`graph_store.py`](graph_store.py:1) for the graph wrapper and
[`audit_log.py`](audit_log.py:1) for the hash-chained audit table.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_PATH = os.environ.get("CYSLOP_DB_PATH", str(Path(__file__).resolve().parent / "cyslop.db"))

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'OPEN',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    phone_numbers TEXT NOT NULL DEFAULT '[]',
    entity_type TEXT NOT NULL DEFAULT 'PERSON',
    base_risk_score REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_entities_case ON entities(case_id);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0.0 AND 1.0),
    evidence_source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PENDING',
    reviewer TEXT DEFAULT '',
    reviewed_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_edges_case ON edges(case_id);

CREATE TABLE IF NOT EXISTS evidence_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id TEXT NOT NULL REFERENCES edges(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL DEFAULT 'GENERIC',
    reference TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_evidence_edge ON evidence_sources(edge_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    case_id TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    current_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id);

CREATE TABLE IF NOT EXISTS users (
    badge_id TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'analyst' CHECK (role IN ('lead_investigator', 'analyst')),
    active_case TEXT NOT NULL DEFAULT 'CAS-2026-102',
    created_at TEXT NOT NULL
);
"""


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def get_db(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ---- F1 Entity Resolution (append-only; existing schema untouched) ----
MERGE_LOG_SQL = """
CREATE TABLE IF NOT EXISTS merge_log (
    id TEXT PRIMARY KEY,
    surviving_entity_id TEXT,
    merged_entity_ids TEXT,
    rule TEXT,
    confidence REAL,
    evidence TEXT,
    decision TEXT,
    decided_by TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_merge_log_survivor ON merge_log(surviving_entity_id);
"""

# ---- F1 source_refs + F2 extraction runs (append-only) ----
ENTITY_SOURCES_SQL = """
CREATE TABLE IF NOT EXISTS entity_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    case_id TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL,
    record_id TEXT NOT NULL DEFAULT '',
    field TEXT DEFAULT '',
    span_start INTEGER,
    span_end INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_entity_sources_entity ON entity_sources(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_sources_case ON entity_sources(case_id);
CREATE TABLE IF NOT EXISTS extraction_runs (
    run_key TEXT PRIMARY KEY,
    case_id TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',
    record_id TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '{}'
);
"""


def ensure_entity_sources_table(db_path: str | None = None) -> None:
    with get_db(db_path) as conn:
        conn.executescript(ENTITY_SOURCES_SQL)


def ensure_merge_log_table(db_path: str | None = None) -> None:
    from datetime import datetime, timezone  # noqa: F401 (kept for future use)
    with get_db(db_path) as conn:
        conn.executescript(MERGE_LOG_SQL)


def init_db(db_path: str | None = None) -> str:
    """Create all tables idempotently. Returns resolved db path."""
    path = db_path or DB_PATH
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(MERGE_LOG_SQL)
        conn.executescript(ENTITY_SOURCES_SQL)
        conn.commit()
    finally:
        conn.close()
    return path


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def dumps_list(values: list[str]) -> str:
    return json.dumps(values or [])


def loads_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return []
