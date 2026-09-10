import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, X } from 'lucide-react';
import { api, ACTIVE_CASE } from '@/lib/api';
import { useAuth } from '@/lib/auth';

type Candidate = {
  id: string; surviving_entity_id: string; merged_entity_ids: string[];
  rule: string; confidence: number; evidence: unknown; decision: string;
};

type Link = { id?: string; link_id?: string; source_id: string; target_id: string; relation_type: string; confidence_score: number; evidence_source: string; status: string };

function AttrTable({ title, entityId }: { title: string; entityId: string }) {
  const d = useQuery({
    queryKey: ['entity', entityId],
    queryFn: () => api.entityDetail(entityId),
    enabled: !!entityId,
  });
  const e = (d.data?.entity || {}) as Record<string, unknown>;
  return (
    <div style={{ flex: 1, border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>{title}: {entityId}</div>
      {d.isSuccess ? (
        <dl style={{ fontSize: 12, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 10px' }}>
          <dt className="muted">name</dt><dd>{String(e.name || '')}</dd>
          <dt className="muted">type</dt><dd>{String(e.entity_type || '')}</dd>
          <dt className="muted">aliases</dt><dd>{JSON.stringify(e.aliases || [])}</dd>
          <dt className="muted">phones</dt><dd>{JSON.stringify((e as { phone_numbers?: string[] }).phone_numbers || [])}</dd>
          <dt className="muted">sources</dt><dd>{String(d.data?.source_refs?.length || 0)} refs</dd>
        </dl>
      ) : (
        <p className="muted" style={{ fontSize: 12 }}>{d.isPending ? 'Loading…' : 'Unavailable'}</p>
      )}
    </div>
  );
}

export default function ReviewQueue() {
  const { auth } = useAuth();
  const caseId = auth?.activeCase || ACTIVE_CASE;
  const qc = useQueryClient();
  const cand = useQuery({
    queryKey: ['candidates', caseId],
    queryFn: async (): Promise<Candidate[]> => {
      const r = await api.candidates(caseId);
      return r.candidates as unknown as Candidate[];
    },
  });
  const decide = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) =>
      accept ? api.acceptCandidate(id) : api.rejectCandidate(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['candidates', caseId] }); qc.invalidateQueries({ queryKey: ['graph', caseId] }); },
  });
  const q = useQuery({
    queryKey: ['pending', caseId],
    queryFn: async (): Promise<Link[]> => {
      try {
        const r = await api.pending(caseId);
        return (r.links as unknown as Link[]).map((l) => ({ ...l, link_id: (l.link_id as string) || (l.id as string) }));
      } catch {
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
        <h1 className="page-title">Review queue — candidate merges</h1>
        <p className="page-subtitle">{cand.data?.length ?? '…'} candidates awaiting Accept / Reject → /resolution/candidates</p></div>
      </div>
      {cand.isError && <div className="auth-error">{(cand.error as Error).message}</div>}
      <div className="panel" style={{ padding: 14, display: 'grid', gap: 12 }}>
        {(cand.data || []).map((c) => {
          const other = c.merged_entity_ids?.[0] || '';
          return (
            <div key={c.id} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
              <div style={{ fontSize: 12, marginBottom: 8 }}>
                <strong>{c.rule}</strong> · conf {Math.round((c.confidence || 0) * 100)}% · <span className="muted">{c.id}</span>
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                <AttrTable title="A" entityId={c.surviving_entity_id} />
                <AttrTable title="B" entityId={other} />
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button className="button-primary" style={{ padding: '7px 12px' }} disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: c.id, accept: true })}><Check size={13} style={{ verticalAlign: 'middle' }} /> Accept</button>
                <button className="button-danger" style={{ padding: '7px 12px' }} disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: c.id, accept: false })}><X size={13} style={{ verticalAlign: 'middle' }} /> Reject</button>
              </div>
            </div>
          );
        })}
        {cand.isSuccess && cand.data.length === 0 && <p className="muted" style={{ fontSize: 12 }}>Queue clear — no pending candidates.</p>}
      </div>
      <div className="page-header" style={{ marginTop: 18 }}>
        <div><h1 className="page-title" style={{ fontSize: 16 }}>Evidence review queue</h1>
        <p className="page-subtitle">{q.data?.length ?? '…'} links awaiting Approve / Reject → POST /api/v1/links/review</p></div>
      </div>
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
