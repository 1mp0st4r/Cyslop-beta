import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, X, Radar } from 'lucide-react';
import { api, ACTIVE_CASE, type Finding } from '@/lib/api';
import { useAuth } from '@/lib/auth';

function badge(sev: string) {
  if (sev === 'high') return 'status-badge status-red';
  if (sev === 'medium') return 'status-badge status-amber';
  return 'status-badge status-green';
}

export default function Findings() {
  const { auth } = useAuth();
  const caseId = auth?.activeCase || ACTIVE_CASE;
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>('');
  const q = useQuery({
    queryKey: ['findings', caseId, filter],
    queryFn: async (): Promise<Finding[]> => {
      const r = await api.findings(caseId, filter || undefined);
      return r.findings;
    },
  });
  const scan = useMutation({
    mutationFn: () => api.scanPatterns(caseId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['findings', caseId] }),
  });
  const decide = useMutation({
    mutationFn: ({ id, dismiss }: { id: string; dismiss: boolean }) =>
      dismiss ? api.dismissFinding(id) : api.confirmFinding(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['findings', caseId] }),
  });

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">Rule-based detection · {caseId}</div>
          <h1 className="page-title">Findings — suspicious patterns</h1>
          <p className="page-subtitle">
            P1 circular flow · P2 burner hub · P3 call-then-transfer · P4 comm burst → POST /patterns/scan
          </p>
        </div>
        <button className="button-primary" style={{ padding: '8px 14px' }}
          disabled={scan.isPending} onClick={() => scan.mutate()}>
          <Radar size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          {scan.isPending ? 'Scanning…' : 'Run scan'}
        </button>
      </div>
      {scan.isSuccess && (
        <p className="muted" style={{ fontSize: 12 }}>
          Scan complete — {scan.data.new_count} new finding(s).
        </p>
      )}
      {q.isError && <div className="auth-error">{(q.error as Error).message}</div>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {['', 'open', 'confirmed', 'dismissed'].map((s) => (
          <button key={s || 'all'} className={filter === s ? 'button-primary' : 'graph-tool'}
            style={{ padding: '6px 12px' }} onClick={() => setFilter(s)}>
            {s || 'all'}
          </button>
        ))}
      </div>
      <div className="panel" style={{ padding: 14, display: 'grid', gap: 12 }}>
        {(q.data || []).map((f) => (
          <div key={f.id} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
              <span className={badge(f.severity)}>{f.severity.toUpperCase()}</span>
              <strong style={{ fontSize: 12 }}>{f.rule_id}</strong>
              <span className="muted mono" style={{ fontSize: 10 }}>
                score {Math.round(f.score * 100)}% · {f.status} · {f.id}
              </span>
            </div>
            <p style={{ fontSize: 13, margin: '4px 0 8px' }}>{f.explanation}</p>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
              {f.entity_ids.map((e) => (
                <a key={e} href="/graph" className="mono"
                  style={{ fontSize: 11, border: '1px solid var(--border)', borderRadius: 12, padding: '2px 9px' }}
                  title="Open in graph">
                  {e}
                </a>
              ))}
            </div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
              {f.evidence.length} evidence ref(s): {f.evidence.slice(0, 3).map((e) => e.detail || e.reference).join(' · ')}
              {f.evidence.length > 3 ? ` (+${f.evidence.length - 3} more)` : ''}
            </div>
            {f.status === 'open' && (
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="button-primary" style={{ padding: '7px 12px' }} disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: f.id, dismiss: false })}>
                  <Check size={13} style={{ verticalAlign: 'middle' }} /> Confirm
                </button>
                <button className="button-danger" style={{ padding: '7px 12px' }} disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: f.id, dismiss: true })}>
                  <X size={13} style={{ verticalAlign: 'middle' }} /> Dismiss
                </button>
              </div>
            )}
          </div>
        ))}
        {q.isSuccess && q.data.length === 0 && (
          <p className="muted" style={{ fontSize: 12 }}>No findings — run a scan.</p>
        )}
      </div>
    </div>
  );
}
