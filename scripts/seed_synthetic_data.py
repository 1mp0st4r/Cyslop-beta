"""Seed synthetic demo data: 10 FIRs, 500 CDRs, 100 bank transactions.

Promised by [`README.md`](README.md:99): `python scripts/seed_synthetic_data.py`.
Writes fixtures under `fixtures/synthetic/` as BOTH JSON (legacy consumers)
and CSV/TXT (Phase-2 ingestion pipeline):
  firs.json / firs.csv / fir_<n>.txt  (free-text FIRs, EN + Hindi sentences)
  cdrs.json / cdrs.csv                (caller, callee, timestamp, duration_sec)
  transactions.json / transactions.csv (from_acct, to_acct, amount, timestamp)

Demo scenario: 3 core suspects linked via shared burner + circular money loop.

Usage:
    python scripts/seed_synthetic_data.py [--seed 42] [--out fixtures/synthetic]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic"

# Core ring (deterministic anchors the pipeline must rediscover)
CORE = [
    {"name": "Ramesh Kumar", "variants": ["R. Kumar", "Ramash"], "phone": "+91-9876543210",
     "acct": "ACC-99884411", "vehicle": "DL-01-AB-4402"},
    {"name": "Suresh Sharma", "variants": ["S. Sharma", "Sureth"], "phone": "+91-9123456780",
     "acct": "ACC-11223344", "vehicle": "HR-26-DK-8821"},
    {"name": "Amit Verma", "variants": ["A. Verma"], "phone": "+91-9988776655",
     "acct": "ACC-55667788", "vehicle": "UP-16-CT-1234"},
]
BURNER_PHONE = "+91-9123000001"  # shared anchor linking the 3 core suspects

PERIPHERAL_NAMES = ["Vikram Singh", "Ravi Patel", "Sanjay Gupta", "Mohan Lal",
                    "Arjun Mehta", "Kavita Rao", "Deepak Yadav", "Pooja Nair"]
PERIPHERAL_PHONES = ["+91-9810010010", "+91-9820020020", "+91-9830030030",
                     "+91-9840040040", "+91-9850050050", "+91-9860060060"]
PERIPHERAL_VEHICLES = ["MH-12-EF-5678", "KA-05-MN-4321", "PB-10-GH-7890"]
LOCATIONS = ["Karol Bagh, Delhi", "Andheri West, Mumbai", "Sector 62, Noida",
             "MG Road, Gurugram", "Connaught Place, Delhi", "Ludhiana, Punjab"]
ORGS = ["Sharma Trading Co.", "City Cooperative Bank", "National Logistics Pvt Ltd"]
SECTIONS = ["379 IPC", "420 IPC", "467 IPC", "120B IPC", "34 IPC"]

HINDI_LINES = [
    "पीड़ित ने थाने में आकर शिकायत दर्ज कराई।",
    "आरोपी रात के समय घटनास्थल के पास देखा गया था।",
    "पुलिस ने कॉल रिकॉर्ड और बैंक लेनदेन की जांच शुरू कर दी है।",
    "चश्मदीद गवाह के बयान दर्ज कर लिए गए हैं।",
]

FIR_TEMPLATES = [
    ("theft", "On {date}, complainant {complainant} reported theft of goods near {loc} under {sec}. "
              "Suspect {suspect} (also recorded as '{variant}') was seen near the scene in vehicle {vehicle}. "
              "The suspect was contacted on {phone} and via burner {burner}. {hindi}"),
    ("fraud", "Complainant {complainant} alleges cheating of Rs. {amount} by {suspect} ('{variant}') "
              "of {org} at {loc} on {date} under {sec}. Payments were routed from {acct}. "
              "Call records show coordination on {phone} / {burner}. {hindi}"),
    ("conspiracy", "FIR {fir_no} dated {date} ({sec}): {suspect} alias '{variant}' conspired with associates "
                   "near {loc}. Vehicle {vehicle} spotted at the location. Complainant: {complainant}. "
                   "Investigating officer seized phone {phone}; burner {burner} appears in CDRs. {hindi}"),
]


def gen_firs(rng: random.Random, n: int = 10):
    firs = []
    for i in range(n):
        core = CORE[i % 3] if i < 6 else None  # first 6 FIRs pin the core ring
        if core:
            suspect, variant = core["name"], rng.choice(core["variants"])
            phone, vehicle, acct = core["phone"], core["vehicle"], core["acct"]
        else:
            suspect = rng.choice(PERIPHERAL_NAMES)
            variant = suspect.split()[0]
            phone = rng.choice(PERIPHERAL_PHONES)
            vehicle = rng.choice(PERIPHERAL_VEHICLES)
            acct = f"ACC-{rng.randint(10000000, 99999999)}"
        kind, tpl = FIR_TEMPLATES[i % len(FIR_TEMPLATES)]
        fir_no = f"FIR #{204 + i}/23"
        date = (datetime(2023, 1, 5) + timedelta(days=i * 9)).date().isoformat()
        text = tpl.format(
            date=date, complainant=rng.choice(PERIPHERAL_NAMES + [c["name"] for c in CORE]),
            loc=rng.choice(LOCATIONS), sec=rng.choice(SECTIONS), suspect=suspect,
            variant=variant, vehicle=vehicle, phone=phone, burner=BURNER_PHONE,
            hindi=rng.choice(HINDI_LINES), fir_no=fir_no, org=rng.choice(ORGS),
            amount=round(rng.uniform(50000, 900000), 2), acct=acct)
        # paragraph-split for evidence_source granularity (para index = click-through target)
        paras = [p.strip() for p in text.split(". ") if p.strip()]
        firs.append({"fir_no": fir_no, "kind": kind, "section": text.split("under ")[-1][:12]
                     if "under" in text else rng.choice(SECTIONS),
                     "date": date, "suspect": suspect, "text": text, "paragraphs": paras,
                     "phones": [phone, BURNER_PHONE], "vehicle": vehicle})
    return firs


def gen_cdrs(rng: random.Random, n: int = 500):
    cdrs = []
    base = datetime(2023, 6, 1, 21, 0, 0)
    core_phones = [c["phone"] for c in CORE]
    pool = core_phones + [BURNER_PHONE] + PERIPHERAL_PHONES
    for i in range(n):
        if i < 43:  # the "43 late night calls over 3 days" evidence edge
            caller, callee = core_phones[0], core_phones[1]
            ts = base + timedelta(hours=i * 1.5)
            dur = rng.randint(120, 1200)
        elif i < 60:  # burner fan-out: each core suspect calls the burner
            caller, callee = core_phones[i % 3], BURNER_PHONE
            ts = base + timedelta(hours=i * 2)
            dur = rng.randint(60, 900)
        else:
            caller, callee = rng.choice(pool), rng.choice(pool)
            if caller == callee:
                callee = rng.choice(pool)
            ts = base + timedelta(minutes=rng.randint(0, 60 * 24 * 30))
            dur = rng.randint(10, 1200)
        cdrs.append({"id": f"CDR-{i + 1:04d}", "caller": caller, "callee": callee,
                     "timestamp": ts.isoformat(), "duration_sec": dur})
    return cdrs


def gen_transactions(rng: random.Random, n: int = 100):
    txns = []
    accounts = [c["acct"] for c in CORE]
    for i in range(n):
        if i < 6:  # circular money loop across the 3 accounts (A->B->C->A x2)
            src, dst = accounts[i % 3], accounts[(i + 1) % 3]
            amt = round(rng.uniform(200000, 500000), 2)
        else:
            src, dst = rng.choice(accounts + ["ACC-00001111", "ACC-00002222"]), rng.choice(accounts)
            amt = round(rng.uniform(5000, 500000), 2)
        txns.append({"id": f"TXN-{i + 1:04d}", "from_acct": src, "to_acct": dst,
                     "from": src, "to": dst, "amount_inr": amt, "amount": amt,
                     "date": (datetime(2023, 7, 1) + timedelta(days=rng.randint(0, 60))).date().isoformat(),
                     "timestamp": (datetime(2023, 7, 1) + timedelta(days=rng.randint(0, 60))).date().isoformat()})
    return txns


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic demo fixtures.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--firs", type=int, default=10)
    ap.add_argument("--cdrs", type=int, default=500)
    ap.add_argument("--txns", type=int, default=100)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    firs = gen_firs(rng, args.firs)
    cdrs = gen_cdrs(rng, args.cdrs)
    txns = gen_transactions(rng, args.txns)

    (args.out / "firs.json").write_text(json.dumps(firs, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "cdrs.json").write_text(json.dumps(cdrs, indent=2), encoding="utf-8")
    (args.out / "transactions.json").write_text(json.dumps(txns, indent=2), encoding="utf-8")

    with open(args.out / "firs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["fir_no", "date", "suspect", "text"])
        w.writeheader()
        for r in firs:
            w.writerow({"fir_no": r["fir_no"], "date": r["date"], "suspect": r["suspect"], "text": r["text"]})
    with open(args.out / "cdrs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["caller", "callee", "timestamp", "duration_sec"])
        w.writeheader()
        for r in cdrs:
            w.writerow({"caller": r["caller"], "callee": r["callee"],
                        "timestamp": r["timestamp"], "duration_sec": r["duration_sec"]})
    with open(args.out / "transactions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["from_acct", "to_acct", "amount", "timestamp"])
        w.writeheader()
        for r in txns:
            w.writerow({"from_acct": r["from_acct"], "to_acct": r["to_acct"],
                        "amount": r["amount_inr"], "timestamp": r["timestamp"]})
    for r in firs:
        safe = "".join(c if c.isalnum() else "_" for c in r["fir_no"])
        (args.out / f"{safe}.txt").write_text(
            f"{r['fir_no']} | {r['date']}\n{r['text']}\n", encoding="utf-8")

    print(f"Wrote {len(firs)} FIRs, {len(cdrs)} CDRs, {len(txns)} transactions -> {args.out}")
    print("Core pattern: 3 suspects share burner", BURNER_PHONE, "+ circular money loop.")


if __name__ == "__main__":
    main()
