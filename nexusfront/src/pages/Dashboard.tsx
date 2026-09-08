import { useQuery } from '@tanstack/react-query';
import { Link } from 'wouter';
import { Activity, AlertTriangle, Users, Smartphone, Landmark } from 'lucide-react';
import { api, ACTIVE_CASE } from '@/lib/api';
import { useAuth } from '@/lib/auth';

export default function Dashboard() {
  const { auth } = useAuth();
  const caseId = auth?.activeCase || ACTIVE_CASE;
  const q = useQuery({ queryKey: ['overview', caseId], queryFn: () => api.overview(caseId) });

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">Operations room · {caseId}</div>
          <h1 className="page-title">Case overview dashboard</h1>
          <p className="page-subtitle">{q.data?.case_title || 'Loading…'} · live from /api/v1/cases/{'{id}'}/overview</p>
        </div>
        <span className="status-badge status-green"><span className="online-pulse" style={{ margin: 0 }} />LIVE FEED</span>
      </div>
      {q.isError && <div className="auth-error">Failed to load overview: {(q.error as Error).message}. Is the FastAPI server running on :8000?</div>}
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-header"><div><h2 className="panel-title">System health</h2><p className="panel-copy">Reported by backend overview endpoint</p></div><Activity size={15} className="accent" /></div>
          <div className="metric-strip">
            <div className="metric"><div className="metric-label">CPU load</div><div className="metric-value">{q.data ? `${q.data.cpu_load_percent}%` : '—'}</div></div>
            <div className="metric"><div className="metric-label">Memory</div><div className="metric-value">{q.data ? `${q.data.memory_usage_percent}%` : '—'}</div></div>
            <div className="metric"><div className="metric-label">Status</div><div className="metric-value green" style={{ fontSize: 16 }}>{q.data?.system_status || '—'}</div></div>
          </div>
        </section>
        <section className="panel">
          <div className="panel-header"><div><h2 className="panel-title">At a glance</h2><p className="panel-copy">Entity counts for {caseId}</p></div><Users size={15} className="accent" /></div>
          <div className="metric-strip">
            <div className="metric"><div className="metric-label"><Users size={11} style={{ verticalAlign: 'middle' }} /> Suspects</div><div className="metric-value">{q.data?.total_suspects ?? '—'}</div></div>
            <div className="metric"><div className="metric-label"><Smartphone size={11} style={{ verticalAlign: 'middle' }} /> Phones</div><div className="metric-value">{q.data?.total_phone_numbers ?? '—'}</div></div>
            <div className="metric"><div className="metric-label"><Landmark size={11} style={{ verticalAlign: 'middle' }} /> Bank accts</div><div className="metric-value">{q.data?.total_bank_accounts ?? '—'}</div></div>
          </div>
          <div className="system-status">
            <span style={{ fontSize: 11 }} className="amber"><AlertTriangle size={12} style={{ verticalAlign: 'middle' }} /> {q.data?.unreviewed_alerts ?? '—'} unreviewed alerts</span>
            <Link href="/review" className="button-secondary" style={{ textDecoration: 'none', padding: '8px 12px' }}>Open review queue</Link>
          </div>
        </section>
      </div>
    </div>
  );
}
