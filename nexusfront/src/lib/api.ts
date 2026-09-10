const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || 'http://127.0.0.1:8000';

export type EntityNode = {
  id: string; name: string; aliases: string[]; phone_numbers: string[];
  entity_type: string; base_risk_score: number;
};
export type GraphEdge = {
  link_id: string; source_id: string; target_id: string; relation_type: string;
  confidence_score: number; evidence_source: string; status: string;
};
export type RiskAssessment = {
  entity_id: string; threat_score: number; risk_level: string; contributing_factors: string[];
};
export type Overview = {
  case_id: string; case_title: string; total_suspects: number; total_phone_numbers: number;
  total_bank_accounts: number; unreviewed_alerts: number; system_status: string;
  cpu_load_percent: number; memory_usage_percent: number;
};
export type AuditEntry = {
  timestamp: string; actor_id: string; action: string; case_id: string;
  previous_hash: string; current_hash: string;
};
export type LoginResponse = {
  status: string; badge_id: string; assigned_role: string; active_case: string;
  access_token: string; token_type: string;
};

function headers(): HeadersInit {
  const token = localStorage.getItem('nexus_token');
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...headers(), ...(init?.headers || {}) },
  });
  if (res.status === 401) {
    localStorage.removeItem('nexus_auth');
    localStorage.removeItem('nexus_token');
    if (!window.location.pathname.includes('/login')) window.location.href = '/login';
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  login: (badge_id: string, password: string) =>
    req<LoginResponse>(
      '/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ badge_id, password }) }),
  me: () => req<{ badge_id: string; role: string; active_case: string }>('/api/v1/auth/me'),
  overview: (caseId: string) => req<Overview>(`/api/v1/cases/${caseId}/overview`),
  graph: (caseId: string) => req<{ case_id: string; nodes: EntityNode[]; edges: GraphEdge[] }>(`/api/v1/cases/${caseId}/graph`),
  risk: (entityId: string, caseId?: string) => req<RiskAssessment>(`/api/v1/suspect/${entityId}/risk${caseId ? `?case_id=${encodeURIComponent(caseId)}` : ''}`),
  batchRisks: (entityIds: string[], caseId: string) =>
    req<{ case_id: string; risks: Record<string, RiskAssessment> }>(
      '/api/v1/suspects/risks', { method: 'POST', body: JSON.stringify({ entity_ids: entityIds, case_id: caseId }) }),
  pending: (caseId: string) => req<{ case_id: string; count: number; links: Record<string, unknown>[] }>(`/api/v1/cases/${caseId}/links/pending`),
  review: (link_id: string, action: 'APPROVE' | 'REJECT', officer_badge: string) =>
    req<{ status: string; link_id: string; decision: string; audit_hash: string }>(
      '/api/v1/links/review', { method: 'POST', body: JSON.stringify({ link_id, action, officer_badge }) }),
  auditVerify: (caseId: string) =>
    req<{ case_id: string; chain_integrity_verified: boolean; anchor: Record<string, unknown>; total_entries: number; entries: AuditEntry[] }>(
      `/api/v1/cases/${caseId}/audit/verify`),
  resolve: (caseId: string) =>
    req<{ auto_merges: string[]; candidates: string[] }>(`/entities/resolve/${caseId}`, { method: 'POST' }),
  entityDetail: (id: string) =>
    req<{ entity: EntityNode & Record<string, unknown>; source_refs: Record<string, unknown>[]; merge_history: Record<string, unknown>[] }>(`/entities/${id}`),
  candidates: (caseId: string) =>
    req<{ case_id: string; count: number; candidates: Record<string, unknown>[] }>(`/resolution/candidates/${caseId}`),
  acceptCandidate: (id: string) =>
    req<Record<string, unknown>>(`/resolution/candidates/${id}/accept`, { method: 'POST' }),
  rejectCandidate: (id: string) =>
    req<Record<string, unknown>>(`/resolution/candidates/${id}/reject`, { method: 'POST' }),
  unmerge: (mergeId: string) =>
    req<Record<string, unknown>>(`/resolution/unmerge/${mergeId}`, { method: 'POST' }),
  ingestText: (caseId: string, source_type: string, text: string, record_id?: string) =>
    req<{ entities_created: number; entities_merged: number; relations_created: number }>(
      `/ingest/text/${caseId}`, { method: 'POST', body: JSON.stringify({ source_type, text, record_id: record_id || '' }) }),
  auditAnchor: (caseId: string) =>
    req<Record<string, unknown>>(`/api/v1/cases/${caseId}/audit/anchor`, { method: 'POST' }),
  scanPatterns: (caseId: string) =>
    req<{ case_id: string; new_count: number; new: Finding[] }>(
      `/patterns/scan/${caseId}`, { method: 'POST' }),
  findings: (caseId: string, status?: string) =>
    req<{ case_id: string; count: number; findings: Finding[] }>(
      `/findings/${caseId}${status ? `?status=${status}` : ''}`),
  confirmFinding: (id: string) =>
    req<Finding>(`/findings/${id}/confirm`, { method: 'POST' }),
  dismissFinding: (id: string) =>
    req<Finding>(`/findings/${id}/dismiss`, { method: 'POST' }),
  logout: () =>
    req<{ session_status: string; total_actions_audited: number; chain_integrity_verified: boolean }>(
      '/api/v1/auth/logout', { method: 'POST' }),
};

export type EvidenceRef = { edge_id: string; source_type: string; reference: string; detail: string };
export type Finding = {
  id: string; rule_id: string; severity: string; score: number; entity_ids: string[];
  explanation: string; evidence: EvidenceRef[]; detected_at: string; status: string;
};

export const ACTIVE_CASE = 'CAS-2026-102';
