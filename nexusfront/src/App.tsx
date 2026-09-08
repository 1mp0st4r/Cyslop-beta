import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Switch, Link, useLocation, Redirect } from 'wouter';
import { Grid2X2, Network, ClipboardList, ScrollText, LogOut, Menu } from 'lucide-react';
import { AuthProvider, useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import Login from '@/pages/Login';
import Dashboard from '@/pages/Dashboard';
import GraphView from '@/pages/GraphView';
import ReviewQueue from '@/pages/ReviewQueue';
import AuditLog from '@/pages/AuditLog';

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15_000 } } });

function Shell() {
  const { auth, setAuth } = useAuth();
  const [loc, nav] = useLocation();
  if (!auth) return <Redirect to="/login" />;
  const logout = async () => {
    try { await api.logout(); } catch { /* still exit locally */ }
    setAuth(null);
    nav('/login');
  };
  const item = (to: string, label: string, Icon: typeof Grid2X2) => (
    <Link href={to} className={`nav-item ${loc === to ? 'active' : ''}`}>
      <Icon size={15} /><span>{label}</span>
    </Link>
  );
  return (
    <div className="console">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-block brand-block-compact">
            <img src="/logo-full.png" alt="NEXUS" className="brand-logo-full" />
            <div className="mvp-chip">SIH26189 MVP</div>
          </div>
        </div>
        <nav className="sidebar-nav">
          <div className="nav-heading eyebrow">Main menu</div>
          {item('/dashboard', 'Dashboard', Grid2X2)}
          {item('/graph', 'Node Graph', Network)}
          {item('/review', 'Evidence Review', ClipboardList)}
          {item('/audit', 'Audit Log', ScrollText)}
          <button className="nav-item" onClick={logout}><LogOut size={15} /><span>Log out ({auth.badge})</span></button>
        </nav>
        <div className="sidebar-spacer" />
        <div className="legend">
          <div className="legend-title">Entity legend</div>
          <div className="legend-row"><span className="legend-dot" style={{ color: '#a13d3d', background: '#a13d3d' }} />High risk (≥70)</div>
          <div className="legend-row"><span className="legend-dot" style={{ color: '#c98a3d', background: '#c98a3d' }} />Medium (40–69)</div>
          <div className="legend-row"><span className="legend-dot" style={{ color: '#6b8f5e', background: '#6b8f5e' }} />Low ({'<40'})</div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span className="mobile-menu"><Menu size={19} /></span>
          <div className="top-title">Case: {auth.activeCase} · {auth.role}</div>
          <div className="user-pill"><span>{auth.badge}</span><span className="user-avatar">OR</span></div>
        </header>
        <Switch>
          <Route path="/dashboard" component={Dashboard} />
          <Route path="/graph" component={GraphView} />
          <Route path="/review" component={ReviewQueue} />
          <Route path="/audit" component={AuditLog} />
          <Route><Redirect to="/dashboard" /></Route>
        </Switch>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <Switch>
          <Route path="/login" component={Login} />
          <Route path="/dashboard"><Shell /></Route>
          <Route path="/graph"><Shell /></Route>
          <Route path="/review"><Shell /></Route>
          <Route path="/audit"><Shell /></Route>
          <Route path="/"><Shell /></Route>
          <Route><Redirect to="/dashboard" /></Route>
        </Switch>
      </AuthProvider>
    </QueryClientProvider>
  );
}
