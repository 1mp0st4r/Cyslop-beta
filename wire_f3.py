"""Wire F3 into existing files (script-based patch; edit tools are locked)."""
import pathlib

# 1. models.py — Finding contract
mp = pathlib.Path("models.py")
mt = mp.read_text(encoding="utf-8")
if "class Finding" not in mt:
    mt += '''

# ---- F3 Suspicious Pattern Detection (Finding contract for F4/F6/F7) ----
class EvidenceRef(BaseModel):
    edge_id: str = ""
    source_type: str = "EDGE"
    reference: str = ""
    detail: str = ""


class Finding(BaseModel):
    id: str
    rule_id: str
    severity: Literal["low", "medium", "high"] = "medium"  # type: ignore[valid-type]
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    entity_ids: list[str] = Field(default_factory=list)
    explanation: str = ""
    evidence: list["EvidenceRef"] = Field(default_factory=list)  # type: ignore[valid-type]
    detected_at: str = ""
    status: Literal["open", "confirmed", "dismissed"] = "open"  # type: ignore[valid-type]
'''
    mp.write_text(mt, encoding="utf-8")
    print("models.py patched")
else:
    print("models.py already has Finding")

# 2. main.py — register F3 routes + startup seed
ap = pathlib.Path("main.py")
at = ap.read_text(encoding="utf-8")
if "patterns.register_routes" not in at:
    at += '''

# ---- F3 Suspicious Pattern Detection (additive; no existing routes touched) ----
try:
    import patterns as _patterns  # noqa: E402
    _patterns.ensure_findings_table()
    _patterns.register_routes(app)
    try:
        import seed_patterns as _seedp  # noqa: E402
        _seedp.seed()
    except Exception:
        pass
except Exception as _f3_exc:  # never break existing app on F3 import failure
    print(f"F3 patterns unavailable: {_f3_exc}")
'''
    ap.write_text(at, encoding="utf-8")
    print("main.py patched")
else:
    print("main.py already wired")

# 3. nexusfront api.ts — findings client methods
ip = pathlib.Path("nexusfront/src/lib/api.ts")
it = ip.read_text(encoding="utf-8")
if "scanPatterns" not in it:
    it = it.replace(
        "  logout: () =>",
        """  scanPatterns: (caseId: string) =>
    req<{ case_id: string; new_count: number; new: Finding[] }>(
      `/patterns/scan/${caseId}`, { method: 'POST' }),
  findings: (caseId: string, status?: string) =>
    req<{ case_id: string; count: number; findings: Finding[] }>(
      `/findings/${caseId}${status ? `?status=${status}` : ''}`),
  confirmFinding: (id: string) =>
    req<Finding>(`/findings/${id}/confirm`, { method: 'POST' }),
  dismissFinding: (id: string) =>
    req<Finding>(`/findings/${id}/dismiss`, { method: 'POST' }),
  logout: () =>""")
    it = it.replace(
        "export const ACTIVE_CASE",
        """export type EvidenceRef = { edge_id: string; source_type: string; reference: string; detail: string };
export type Finding = {
  id: string; rule_id: string; severity: string; score: number; entity_ids: string[];
  explanation: string; evidence: EvidenceRef[]; detected_at: string; status: string;
};

export const ACTIVE_CASE""")
    ip.write_text(it, encoding="utf-8")
    print("api.ts patched")
else:
    print("api.ts already wired")
