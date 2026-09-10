"""Wire F4 (script-based patch; edit tools are locked on patterns.py/main.py)."""
import pathlib

# 1. patterns.py — include anomaly detectors in scan_case + /analyze/scan alias
pp = pathlib.Path("patterns.py")
pt = pp.read_text(encoding="utf-8")
if "import anomaly as _anom" not in pt:
    old = """    dets = [
        *detect_circular_flow(edges, details, cfg),
        *detect_burner_hub(edges, details, cfg),
        *detect_call_then_transfer(edges, details, cfg),
        *detect_comm_burst(edges, details, cfg),
    ]"""
    new = """    dets = [
        *detect_circular_flow(edges, details, cfg),
        *detect_burner_hub(edges, details, cfg),
        *detect_call_then_transfer(edges, details, cfg),
        *detect_comm_burst(edges, details, cfg),
    ]
    try:
        import anomaly as _anom  # F4: same Finding contract / dedup machinery
        dets += [
            *_anom.detect_amount_outlier(edges, details),
            *_anom.detect_volume_spike(edges, details),
            *_anom.detect_counterparty_expansion(edges, details),
            *_anom.detect_odd_hour(edges, details),
        ]
        for _d in dets:
            if _d["rule_id"].startswith("A") and _d.get("severity"):
                SEVERITY[_d["rule_id"]] = _d["severity"]
    except Exception:
        pass"""
    assert old in pt, "scan_case block not found"
    pt = pt.replace(old, new)
    # alias route inside register_routes: add after _scan definition
    old2 = "        return scan_case(case_id)\n"
    new2 = ("        return scan_case(case_id)\n"
            "\n"
            "    @app.post(\"/analyze/scan/{case_id}\", tags=[\"Patterns\"])\n"
            "    def _analyze_scan(case_id: str, role: str = role_dep):  # type: ignore[no-untyped-def]\n"
            "        if _has_auth:\n"
            "            try:\n"
            "                _log(role, \"SCAN_ANALYZE\", case_id)\n"
            "            except Exception:\n"
            "                pass\n"
            "        return scan_case(case_id)\n")
    assert old2 in pt, "register_routes anchor not found"
    pt = pt.replace(old2, new2)
    pp.write_text(pt, encoding="utf-8")
    print("patterns.py patched for F4")
else:
    print("patterns.py already wired for F4")

# 2. main.py — register anomaly routes + seed anomalies at startup
mp = pathlib.Path("main.py")
mt = mp.read_text(encoding="utf-8")
if "anomaly" not in mt:
    old = """    try:
        import seed_patterns as _seedp  # noqa: E402
        _seedp.seed()
    except Exception:
        pass"""
    new = """    try:
        import seed_patterns as _seedp  # noqa: E402
        _seedp.seed()
    except Exception:
        pass
    try:
        import anomaly as _anomaly  # noqa: E402  (F4 statistical detectors)
        _anomaly.register_routes(app)
        _anomaly.seed_anomalies()
    except Exception as _f4_exc:
        print(f"F4 anomaly unavailable: {_f4_exc}")"""
    assert old in mt, "main.py seed anchor not found"
    mt = mt.replace(old, new)
    mp.write_text(mt, encoding="utf-8")
    print("main.py patched for F4")
else:
    print("main.py already wired for F4")
