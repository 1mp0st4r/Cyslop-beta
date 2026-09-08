import { useQuery } from '@tanstack/react-query';
import { ShieldCheck, ShieldX } from 'lucide-react';
import { api, ACTIVE_CASE } from '@/lib/api';
import { useAuth } from '@/lib/auth';

export default function AuditLog() {
  const { auth } = useAuth();
  const caseId = auth?.activeCase || ACTIVE_CASE;
  const q = useQuery({ queryKey: ['audit', caseId], queryFn: () => api.auditVerify(caseId) });

  return (
    <div className="page">
      <div className="page-header">
        <div><div className="eyebrow">Chain-of-custody · {caseId}</div>
        <h1 className="page-title">Audit log viewer</h1>
        <p className="page-subtitle">Hash-chained ledger from verify_audit_chain()</p></div>
        {q.data && (
          q.data.chain_integrity_verified
            ? <span className="status-badge status-green"><ShieldCheck size={12} /> chain verified ✅</span>
            : <span className="status-badge status-red"><ShieldX size={12} /> chain broken ❌</span>
        )}
      </div>
      {q.isError && <div className="auth-error">{(q.error as Error).message}</div>}
      <div className="panel" style={{ overflow: 'auto' }}>
        <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
          <thead><tr className="muted" style={{ textAlign: 'left' }}>
            <th style={{ padding: '10px 12px' }}>Timestamp</th><th style={{ padding: '10px 12px' }}>Actor</th>
            <th style={{ padding: '10px 12px' }}>Action</th><th style={{ padding: '10px 12px' }}>Prev hash</th><th style={{ padding: '10px 12px' }}>Hash</th>
          </tr></thead>
          <tbody>
            {(q.data?.entries || []).map((e, i) => (
              <tr key={`${e.current_hash}-${i}`} style={{ borderTop: '1px solid var(--line)' }}>
                <td className="mono" style={{ padding: '8px 12px' }}>{e.timestamp}</td>
                <td style={{ padding: '8px 12px' }}>{e.actor_id}</td>
                <td style={{ padding: '8px 12px' }}>{e.action}</td>
                <td className="mono faint" style={{ padding: '8px 12px' }}>{e.previous_hash.slice(0, 12)}…</td>
                <td className="mono" style={{ padding: '8px 12px' }}>{e.current_hash.slice(0, 12)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
