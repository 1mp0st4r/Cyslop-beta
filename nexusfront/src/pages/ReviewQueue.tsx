import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, X } from 'lucide-react';
import { api, ACTIVE_CASE } from '@/lib/api';
import { useAuth } from '@/lib/auth';

type Link = { id?: string; link_id?: string; source_id: string; target_id: string; relation_type: string; confidence_score: number; evidence_source: string; status: string };

export default function ReviewQueue() {
  const { auth } = useAuth();
  const caseId = auth?.activeCase || ACTIVE_CASE;
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ['pending', caseId],
    queryFn: async (): Promise<Link[]> => {
      try {
        const r = await api.pending(caseId);
        return (r.links as unknown as Link[]).map((l) => ({ ...l, link_id: (l.link_id as string) || (l.id as string) }));
      } catch {
        // Fallback: derive from graph edges when endpoint unavailable.
        const g = await api.graph(caseId);
        return g.edges.filter((e) => e.status?.toUpperCase().includes('PEND') || e.status?.toUpperCase().includes('UNREV'))
          .map((e) => ({ ...e, id: e.link_id }));
      }
    },
  });
  const m = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'APPROVE' | 'REJECT' }) =>
      api.review(id, action, auth?.badge || 'OFFICER-4402'),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['pending', caseId] }); qc.invalidateQueries({ queryKey: ['graph', caseId] }); },
  });

  return (
    <div className="page">
      <div className="page-header">
        <div><div className="eyebrow">Human-in-the-loop · {caseId}</div>
        <h1 className="page-title">Evidence review queue</h1>
        <p className="page-subtitle">{q.data?.length ?? '…'} links awaiting Approve / Reject → POST /api/v1/links/review</p></div>
      </div>
      {q.isError && <div className="auth-error">{(q.error as Error).message}</div>}
      <div className="panel" style={{ padding: 14 }}>
        {(q.data || []).map((l) => {
          const lid = l.link_id || l.id || '';
          return (
            <div className="data-row" key={lid} style={{ fontSize: 12, alignItems: 'center' }}>
              <span style={{ flex: 1 }}><strong style={{ color: 'var(--text)' }}>{l.relation_type}</strong> · {l.source_id} → {l.target_id} · {Math.round(l.confidence_score * 100)}% · <span className="muted">{l.evidence_source}</span></span>
              <span style={{ display: 'flex', gap: 8 }}>
                <button className="button-primary" style={{ padding: '7px 12px' }} disabled={m.isPending}
                  onClick={() => m.mutate({ id: lid, action: 'APPROVE' })}><Check size={13} style={{ verticalAlign: 'middle' }} /> Approve</button>
                <button className="button-danger" style={{ padding: '7px 12px' }} disabled={m.isPending}
                  onClick={() => m.mutate({ id: lid, action: 'REJECT' })}><X size={13} style={{ verticalAlign: 'middle' }} /> Reject</button>
              </span>
            </div>
          );
        })}
        {q.isSuccess && q.data.length === 0 && <p className="muted" style={{ fontSize: 12 }}>Queue clear — no PENDING_REVIEW links.</p>}
      </div>
    </div>
  );
}
