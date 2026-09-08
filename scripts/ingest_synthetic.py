"""Run Phase-2 ingestion: synthetic fixtures -> SQLite graph.

Usage:
    python scripts/ingest_synthetic.py [--dir fixtures/synthetic]
        [--case CAS-2026-102] [--model en_core_web_sm]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingestion.build_graph import ingest_synthetic_dir

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic"


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest synthetic fixtures into graph store.")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--case", default="CAS-2026-102")
    ap.add_argument("--model", default="en_core_web_sm")
    args = ap.parse_args()
    summary = ingest_synthetic_dir(args.dir, args.case, args.model)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
