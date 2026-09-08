"""Seed synthetic demo data: 10 FIRs, 500 CDRs, 100 bank transactions.

Promised by [`README.md`](README.md:99): `python scripts/seed_synthetic_data.py`.
Writes JSON fixtures under `fixtures/` (git-ignored sample output goes to
`fixtures/synthetic/`), and prints the summary the demo scenario expects:
3 core suspects linked via a shared burner phone + circular money loop.

Usage:
    python scripts/seed_synthetic_data.py [--seed 42] [--out fixtures/synthetic]
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic"

NAMES = [
    "Ramesh Kumar", "Suresh Sharma", "Amit Verma", "Vikram Singh",
    "Ravi Patel", "Sanjay Gupta", "Mohan Lal", "Arjun Mehta",
]
PHONES = [f"+91-98{random.randint(10000000, 99999999)}" for _ in range(20)]
BURNER_PHONE = "+91-9123000001"  # shared anchor linking the 3 core suspects
SECTIONS = ["379 IPC", "420 IPC", "467 IPC", "120B IPC", "34 IPC"]


def gen_firs(rng: random.Random, n: int = 10):
    firs = []
    for i in range(n):
        firs.append(
            {
                "fir_no": f"FIR #{204 + i}/23",
                "section": rng.choice(SECTIONS),
                "complainant": rng.choice(NAMES),
                "summary": f"Mock FIR {i + 1}: suspect linked via {BURNER_PHONE if i < 3 else rng.choice(PHONES)}",
                "date": (datetime(2023, 1, 5) + timedelta(days=i * 9)).date().isoformat(),
            }
        )
    return firs


def gen_cdrs(rng: random.Random, n: int = 500):
    cdrs = []
    base = datetime(2023, 6, 1, 21, 0, 0)
    core = ["+91-9876543210", "+91-9123456780", BURNER_PHONE]
    for i in range(n):
        if i < 43:  # the "43 late night calls over 3 days" evidence edge
            caller, callee = core[0], core[1]
            ts = base + timedelta(hours=i * 1.5)
        else:
            caller, callee = rng.choice(PHONES), rng.choice(PHONES)
            ts = base + timedelta(minutes=rng.randint(0, 60 * 24 * 30))
        cdrs.append(
            {
                "id": f"CDR-{i + 1:04d}",
                "caller": caller,
                "callee": callee,
                "timestamp": ts.isoformat(),
                "duration_sec": rng.randint(10, 1200),
            }
        )
    return cdrs


def gen_transactions(rng: random.Random, n: int = 100):
    txns = []
    accounts = ["ACC-99884411", "ACC-11223344", "ACC-55667788"]
    for i in range(n):
        if i < 3:  # circular money loop across the 3 accounts
            src, dst = accounts[i % 3], accounts[(i + 1) % 3]
        else:
            src, dst = rng.choice(accounts), rng.choice(accounts)
        txns.append(
            {
                "id": f"TXN-{i + 1:04d}",
                "from": src,
                "to": dst,
                "amount_inr": round(rng.uniform(5000, 500000), 2),
                "date": (datetime(2023, 7, 1) + timedelta(days=rng.randint(0, 60))).date().isoformat(),
            }
        )
    return txns


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic demo fixtures.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    firs = gen_firs(rng)
    cdrs = gen_cdrs(rng)
    txns = gen_transactions(rng)

    (args.out / "firs.json").write_text(json.dumps(firs, indent=2), encoding="utf-8")
    (args.out / "cdrs.json").write_text(json.dumps(cdrs, indent=2), encoding="utf-8")
    (args.out / "transactions.json").write_text(json.dumps(txns, indent=2), encoding="utf-8")

    print(f"Wrote {len(firs)} FIRs, {len(cdrs)} CDRs, {len(txns)} transactions -> {args.out}")
    print("Core pattern: 3 suspects share burner", BURNER_PHONE, "+ circular money loop.")


if __name__ == "__main__":
    main()
