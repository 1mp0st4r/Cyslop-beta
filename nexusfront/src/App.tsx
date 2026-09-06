import { useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowLeft, BarChart3, Check, ChevronRight, CircleDot,
  ClipboardList, Clock3, FileSearch, Fingerprint, FolderOpen, Grid2X2, KeyRound,
  Link2, LockKeyhole, LogOut, Menu, Network, Search, ShieldCheck, Smartphone,
  UserRound, X, ZoomIn, ZoomOut,
} from 'lucide-react';

type Screen = 'auth' | 'console' | 'terminated';
type View = 'dashboard' | 'cases' | 'case' | 'graph';
type NodeKind = 'suspect' | 'phone' | 'bank';

type CaseRecord = {
  id: string;
  title: string;
  summary: string;
  status: 'Prioritized' | 'Active' | 'Prescient';
  suspects: string[];
  links: number;
};

const cases: CaseRecord[] = [
  { id: 'CAS-2026-101', title: 'Organized Redline', summary: 'Cross-border collection and shell entities', status: 'Active', suspects: ['Ramesh Kumar', 'Kamest Alpha'], links: 14 },
  { id: 'CAS-2026-102', title: 'Operation Redline', summary: 'Financial fraud / hawala movement', status: 'Prioritized', suspects: ['Suresh Sharma', 'Ramesh Kumar', 'Kamest Alpha'], links: 27 },
  { id: 'CAS-2026-105', title: 'Vehicle Ring', summary: 'Interstate movement of unregistered vehicles', status: 'Prescient', suspects: ['Anamed Sharma', 'Taurraan'], links: 11 },
  { id: 'CAS-2026-107', title: 'Hawala Alpha', summary: 'Hawala movement through dormant accounts', status: 'Prioritized', suspects: ['Suresh Sharma', 'Hawala Alpha'], links: 19 },
  { id: 'CAS-2026-110', title: 'Organized Cell-C', summary: 'Coordinated transfers and proxy SIMs', status: 'Prioritized', suspects: ['Ramesh Kumar', 'Joned Liatma'], links: 23 },
  { id: 'CAS-2026-120', title: 'Organized Cell-E', summary: 'Suspected beneficiary network', status: 'Active', suspects: ['Kainta Panamurch', 'Suresh Sharma'], links: 9 },
];

const graphNodes: { id: string; label: string; kind: NodeKind; x: number; y: number; sub?: string }[] = [
  { id: 'ramesh', label: 'Ramesh Kumar', kind: 'suspect', x: 215, y: 105 },
  { id: 'phone1', label: '+91 9876...', kind: 'phone', x: 92, y: 225 },
  { id: 'phone2', label: '+91 9123...', kind: 'phone', x: 420, y: 100 },
  { id: 'suresh', label: 'Suresh Sharma', kind: 'suspect', x: 305, y: 220 },
  { id: 'dl01', label: 'DL01-AC...', kind: 'bank', x: 555, y: 215 },
  { id: 'suresh2', label: 'Suresh Sharma', kind: 'suspect', x: 210, y: 365 },
  { id: 'phone3', label: '+91 9123...', kind: 'phone', x: 425, y: 380 },
  { id: 'account', label: 'Acc. #9988...', kind: 'bank', x: 553, y: 336 },
];

const edges = [
  ['ramesh', 'phone1', 'OWNS_PHONE', false],
  ['ramesh', 'phone2', 'OWNS_PHONE', false],
  ['ramesh', 'suresh', 'PARTNER_REL', false],
  ['phone1', 'suresh', 'OWNS_PHONE', false],
  ['phone1', 'suresh2', 'OWNS_PHONE', false],
  ['phone2', 'suresh', 'FREQUENT_CALLS', false],
  ['suresh', 'dl01', 'FREQUENT_CALLS', false],
  ['suresh', 'account', 'APPROVED', false],
  ['suresh2', 'suresh', 'FREQUENT_CALLS', false],
  ['suresh2', 'phone3', 'FREQUENT_CALLS', false],
  ['suresh2', 'account', 'SUSPICIOUS_TRANSFER', true],
] as const;

type RelationshipKey = 'OWNS_PHONE' | 'PARTNER_REL' | 'FREQUENT_CALLS' | 'APPROVED' | 'SUSPICIOUS_TRANSFER';

type RelationshipDetail = {
  id: string;
  title: string;
  confidence: string;
  status: 'PENDING REVIEW' | 'APPROVED' | 'UNREVIEWED';
  summary: string;
  source: string;
  timeline: { time: string; title: string; detail: string }[];
  callLogs: { name: string; detail: string }[];
  transactionLogs: { name: string; detail: string }[];
  reviewable: boolean;
};

const relationshipDetails: Record<RelationshipKey, RelationshipDetail> = {
  SUSPICIOUS_TRANSFER: {
    id: 'LINK-8831',
    title: 'SUSPICIOUS_TRANSFER',
    confidence: '88% confidence',
    status: 'PENDING REVIEW',
    summary: 'COR Analytics found a coordinated transfer pattern between Suresh Sharma and account #9988. Three deposits arrived within 11 minutes of late-night calls from the same device cluster.',
    source: 'COR Analytics · call and transaction correlation',
    reviewable: true,
    timeline: [
      { time: '06 FEB · 01:42 IST', title: 'Night call initiated', detail: 'Suresh Sharma called the +91 9123… device for 04m 18s.' },
      { time: '06 FEB · 01:51 IST', title: 'First transfer received', detail: '₹ 2,40,000 credited to Account #9988 from a dormant beneficiary.' },
      { time: '06 FEB · 01:54 IST', title: 'Second transfer received', detail: '₹ 91,500 credited from Hawala Alpha, split across two references.' },
      { time: '06 FEB · 02:03 IST', title: 'Funds dispersed', detail: '₹ 1,20,000 moved to a vehicle-linked account in Delhi.' },
    ],
    callLogs: [
      { name: 'Suresh Sharma', detail: '91 912020 · 04m 18s' },
      { name: 'Ramesh Kumar', detail: '91 915000 · 02m 44s' },
      { name: 'Hawala Alpha', detail: '91 912000 · 01m 12s' },
    ],
    transactionLogs: [
      { name: 'Account #9988', detail: '₹ 2,40,000 · 02:51' },
      { name: 'Hawala Alpha', detail: '₹ 91,500 · 02:54' },
      { name: 'Vehicle account', detail: '₹ 1,20,000 · 03:03' },
    ],
  },
  FREQUENT_CALLS: {
    id: 'LINK-7294',
    title: 'FREQUENT_CALLS',
    confidence: '94% confidence',
    status: 'UNREVIEWED',
    summary: 'The two numbers exchange a concentrated burst of calls immediately before and after account activity. The cadence is unusual for personal contact and matches the wider Hawala Alpha cluster.',
    source: 'Telecom metadata · 3-day call pattern',
    reviewable: true,
    timeline: [
      { time: '04 FEB · 22:18 IST', title: 'Contact begins', detail: 'Three calls placed within 17 minutes from the Suresh Sharma device.' },
      { time: '05 FEB · 00:07 IST', title: 'Pattern repeats', detail: 'Six short calls exchanged while the linked account was accessed.' },
      { time: '05 FEB · 18:42 IST', title: 'Coordinated silence', detail: 'Both devices went dark for 11 minutes after an outgoing transfer.' },
      { time: '06 FEB · 02:03 IST', title: 'Final call before movement', detail: 'A 01m 12s call preceded the dispersal transaction.' },
    ],
    callLogs: [
      { name: 'Suresh Sharma', detail: '14 calls · 18m 42s' },
      { name: 'Ramesh Kumar', detail: '09 calls · 11m 06s' },
      { name: 'Hawala Alpha', detail: '06 calls · 07m 15s' },
    ],
    transactionLogs: [
      { name: 'Account #9988', detail: '03 accesses · 02:51' },
      { name: 'DL01-AC…', detail: '01 access · 03:03' },
    ],
  },
  APPROVED: {
    id: 'LINK-5618',
    title: 'APPROVED',
    confidence: '99% confidence',
    status: 'APPROVED',
    summary: 'The primary subject is a verified owner of this beneficiary account. The relationship is retained as context, while the transaction behavior around it remains under review.',
    source: 'MHA entity registry · officer verified',
    reviewable: false,
    timeline: [
      { time: '18 JAN · 10:14 IST', title: 'Account registered', detail: 'Account #9988 appeared in the MHA entity registry under Suresh Sharma.' },
      { time: '02 FEB · 09:20 IST', title: 'Ownership confirmed', detail: 'Officer review matched the account identifier to the primary subject.' },
      { time: '06 FEB · 02:51 IST', title: 'Activity observed', detail: 'The account received funds during the suspicious movement window.' },
    ],
    callLogs: [
      { name: 'Suresh Sharma', detail: 'Owner record · verified' },
      { name: 'MHA registry', detail: 'Last check · 09:20' },
    ],
    transactionLogs: [
      { name: 'Account #9988', detail: 'Owner context · active' },
      { name: 'Incoming funds', detail: '₹ 2,40,000 · 02:51' },
    ],
  },
  OWNS_PHONE: {
    id: 'LINK-3102',
    title: 'OWNS_PHONE',
    confidence: '96% confidence',
    status: 'APPROVED',
    summary: 'The phone number is registered to the subject identity and was present in the same device cluster as the case’s high-priority calls.',
    source: 'Subscriber registry · device intelligence',
    reviewable: false,
    timeline: [
      { time: '12 DEC · 16:11 IST', title: 'Subscriber match', detail: 'Subscriber records mapped the number to the subject identity.' },
      { time: '03 FEB · 08:32 IST', title: 'Device fingerprint seen', detail: 'The device fingerprint matched the primary investigation handset.' },
      { time: '06 FEB · 02:03 IST', title: 'Active during transfer', detail: 'The number connected to the network immediately before funds moved.' },
    ],
    callLogs: [
      { name: 'Registered owner', detail: 'Suresh Sharma · verified' },
      { name: 'Last active call', detail: '01m 12s · 02:03' },
    ],
    transactionLogs: [
      { name: 'Device cluster', detail: '03 related entities' },
      { name: 'SIM status', detail: 'Active · 06 FEB' },
    ],
  },
  PARTNER_REL: {
    id: 'LINK-4487',
    title: 'PARTNER_REL',
    confidence: '78% confidence',
    status: 'UNREVIEWED',
    summary: 'Ramesh Kumar and Suresh Sharma show a repeated coordination pattern across calls, travel records, and shared beneficiaries. The link is contextual, not yet conclusive.',
    source: 'Cross-case correlation · 4 active investigations',
    reviewable: true,
    timeline: [
      { time: '28 JAN · 21:04 IST', title: 'First shared contact', detail: 'Both subjects appeared in the same call cluster for the first time.' },
      { time: '01 FEB · 13:28 IST', title: 'Shared beneficiary', detail: 'A common beneficiary account appeared in both subjects’ transaction histories.' },
      { time: '05 FEB · 19:16 IST', title: 'Location overlap', detail: 'Device telemetry placed both subjects in the same transit corridor.' },
    ],
    callLogs: [
      { name: 'Ramesh Kumar', detail: '09 calls · 11m 06s' },
      { name: 'Suresh Sharma', detail: '14 calls · 18m 42s' },
    ],
    transactionLogs: [
      { name: 'Shared beneficiary', detail: '02 references · ₹ 3,31,500' },
      { name: 'Travel corridor', detail: 'Delhi → Jaipur · 05 FEB' },
    ],
  },
};

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand-block${compact ? ' brand-block-compact' : ''}`}>
      <img src="/logo-full.png" alt="NEXUS Forensics — Connect the dots" className="brand-logo-full" />
      <div className="mvp-chip">SIH26189 MVP</div>
    </div>
  );
}

function AuthScreen({ onAuthorize }: { onAuthorize: () => void }) {
  const [badge, setBadge] = useState('OFFICER-4402');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const authorize = () => {
    if (!badge.trim() || password.length < 4) {
      setError('Enter a valid badge ID and access key to continue.');
      return;
    }
    onAuthorize();
  };
  return (
    <main className="auth-page">
      <section className="auth-card" data-testid="auth-card">
        <Brand />
        <div className="auth-orbit"><LockKeyhole className="auth-lock" size={44} strokeWidth={1.2} /></div>
        <h1 className="auth-title">NEXUS · Secure Access</h1>
        <p className="auth-copy">Restricted investigation workstation. Every action is logged against your officer identity.</p>
        {error && <div className="auth-error" data-testid="status-auth-error">{error}</div>}
        <label className="field-label" htmlFor="badge">Officer badge ID</label>
        <div className="input-wrap">
          <Fingerprint size={16} />
          <input id="badge" className="text-input" value={badge} onChange={(e) => setBadge(e.target.value)} placeholder="OFFICER-4402" data-testid="input-badge" />
        </div>
        <label className="field-label" htmlFor="password">Access key</label>
        <div className="input-wrap">
          <KeyRound size={16} />
          <input id="password" type="password" className="text-input" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && authorize()} placeholder="Enter secure access key" data-testid="input-password" />
        </div>
        <button className="button-primary button-wide" onClick={authorize} data-testid="button-authorize">AUTHORIZE ACCESS <ChevronRight size={15} style={{ verticalAlign: 'middle' }} /></button>
        <p className="auth-foot"><ShieldCheck size={13} style={{ verticalAlign: 'middle', marginRight: 5 }} />MHA Internal System · Audit logging enabled</p>
      </section>
    </main>
  );
}

function StatusBadge({ status }: { status: CaseRecord['status'] }) {
  return <span className={`status-badge ${status === 'Prioritized' ? 'status-amber' : status === 'Active' ? 'status-green' : 'status-red'}`}>{status}</span>;
}

function Sidebar({ view, setView, open, onLogout }: { view: View; setView: (view: View) => void; open: boolean; onLogout: () => void }) {
  const items: { id: View; label: string; icon: typeof Grid2X2 }[] = [
    { id: 'dashboard', label: 'Dashboard', icon: Grid2X2 },
    { id: 'cases', label: 'Cases / Investigations', icon: FolderOpen },
    { id: 'graph', label: 'Node Graph', icon: Network },
    { id: 'case', label: 'Evidence Inspector', icon: FileSearch },
  ];
  return (
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      <div className="sidebar-brand"><Brand compact /></div>
      <nav className="sidebar-nav">
        <div className="nav-heading eyebrow">Main menu</div>
        {items.map(({ id, label, icon: Icon }) => (
          <button key={id} className={`nav-item ${view === id ? 'active' : ''}`} onClick={() => setView(id)} data-testid={`button-nav-${id}`}>
            <Icon size={15} /><span>{label}</span>
          </button>
        ))}
        <button className="nav-item" onClick={onLogout} data-testid="button-logout"><LogOut size={15} /><span>Log out</span></button>
      </nav>
      <div className="sidebar-spacer" />
      <div className="legend">
        <div className="legend-title">Entity legend</div>
        <div className="legend-row"><span className="legend-dot" style={{ color: '#a13d3d', background: '#a13d3d' }} />Suspect / person of interest</div>
        <div className="legend-row"><span className="legend-dot" style={{ color: '#6f83a0', background: '#6f83a0' }} />Phone number</div>
        <div className="legend-row"><span className="legend-dot" style={{ color: '#6b8f5e', background: '#6b8f5e' }} />Bank account / vehicle</div>
        <div className="legend-row"><span style={{ width: 17, height: 1, background: 'var(--green)' }} />Approved connection</div>
        <div className="legend-row"><span style={{ width: 17, height: 1, background: 'var(--amber)' }} />Unreviewed / suspicious</div>
      </div>
    </aside>
  );
}

function Topbar({ view, onMenu, onLogout }: { view: View; onMenu: () => void; onLogout: () => void }) {
  const title = view === 'dashboard' ? 'Global Overview · All Active Investigations' : view === 'cases' ? 'Cases / Investigations' : 'Case: CAS-2026-102 · Operation Redline';
  return (
    <header className="topbar">
      <button className="mobile-menu" onClick={onMenu} data-testid="button-mobile-menu"><Menu size={19} /></button>
      <div className="top-title">{title}</div>
      <div className="top-search"><Search size={14} /><input aria-label="Search entities" placeholder="Search suspect, phone, whole..." data-testid="input-global-search" /></div>
      <div className="user-pill"><span>OFFICER-4402</span><button className="user-avatar" onClick={onLogout} title="End session" data-testid="button-user-menu">OR</button></div>
    </header>
  );
}

function HealthChart() {
  return (
    <div className="health-body">
      <div className="health-chart">
        <svg className="sparkline" viewBox="0 0 720 100" preserveAspectRatio="none" aria-label="System health chart">
          <path d="M0 75 L14 68 27 78 39 54 53 64 66 40 80 58 96 47 112 69 127 43 142 56 158 36 175 62 191 45 208 74 226 68 243 78 258 65 273 71 291 41 305 61 322 49 340 70 358 73 375 55 390 65 406 59 423 72 439 64 454 75 470 71 486 44 500 60 516 39 532 66 548 54 564 75 580 71 594 22 611 53 626 40 642 65 657 49 674 65 691 28 706 50 720 20" fill="none" stroke="#6fa8e9" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <path d="M0 88 L720 89" fill="none" stroke="#6b8f5e" strokeWidth="1.5" opacity=".8" vectorEffect="non-scaling-stroke" />
        </svg>
      </div>
      <div className="chart-label"><span><i className="key" style={{ background: '#6fa8e9' }} />CPU Load</span><span><i className="key" style={{ background: '#6b8f5e' }} />Memory Usage</span></div>
    </div>
  );
}

function AlertList() {
  const alerts = [
    ['Ramesh Kumar Approved Iffind', 'Unreviewed Links of cases', 'Prioritized ago'],
    ['Suresh Sharma Approved approved', 'Approved Links of cases', 'Prioritized ago'],
    ['Newly Detected Connections from IMAGE 0', 'Unreviewed Links of cases', '3 ways ago'],
    ['Newly Detected Connections from IMAGE 1', 'Unreviewed Links of cases', '7 ways ago'],
  ];
  return <div className="alert-list">{alerts.map((a, i) => <div className="alert-row" key={a[0]}><div className="alert-icon"><AlertTriangle size={12} /></div><div className="alert-main"><strong>{a[0]}</strong><span>{a[1]}</span></div><span className="alert-time">{a[2]}</span></div>)}</div>;
}

function Dashboard({ openCase }: { openCase: () => void }) {
  return (
    <div className="page">
      <div className="page-header"><div><div className="eyebrow">Operations room · 06 FEB 2026 / 14:22 IST</div><h1 className="page-title">Case: GLOBAL OVERVIEW</h1><p className="page-subtitle">All active investigations · System health across monitored entities</p></div><span className="status-badge status-green"><span className="online-pulse" style={{ margin: 0 }} />LIVE FEED</span></div>
      <div className="dashboard-grid">
        <section className="panel"><div className="panel-header"><div><h2 className="panel-title">System health</h2><p className="panel-copy">System liability, chatter commonly correlated across</p></div><span className="mono muted" style={{ fontSize: 10 }}>DATA PLAN · 30D</span></div><HealthChart /></section>
        <section className="panel"><div className="panel-header"><div><h2 className="panel-title">At a glance</h2><p className="panel-copy">Current investigation load</p></div><Activity size={15} className="accent" /></div><div className="metric-strip"><div className="metric"><div className="metric-label">Active cases</div><div className="metric-value">06</div></div><div className="metric"><div className="metric-label">Linked entities</div><div className="metric-value">148</div></div><div className="metric"><div className="metric-label">Needs review</div><div className="metric-value amber">03</div></div></div><div className="system-status"><span className="muted" style={{ fontSize: 11 }}><span className="online-pulse" />All services operational</span><span className="mono faint" style={{ fontSize: 10 }}>99.97% uptime</span></div></section>
        <section className="panel"><div className="panel-header"><div><h2 className="panel-title">Recent alerts</h2><p className="panel-copy">Global alerts across all cases</p></div><AlertTriangle size={15} className="amber" /></div><AlertList /></section>
        <section className="panel"><div className="panel-header"><div><h2 className="panel-title">My active cases</h2><p className="panel-copy">Priority investigations assigned to you</p></div><button className="close-button" onClick={openCase} data-testid="button-open-priority-case"><ChevronRight size={16} /></button></div><div className="case-list">{cases.slice(1, 4).map((item) => <div className="active-case" key={item.id} onClick={openCase} data-testid={`card-active-case-${item.id}`}><div className="case-icon"><Link2 size={14} /></div><div className="case-info"><strong>{item.id}: {item.title}</strong><span>Summary: {item.summary}</span></div><span className="case-state"><Check size={14} /></span></div>)}</div></section>
        <section className="panel span-two"><div className="panel-header"><div><h2 className="panel-title">Investigation pulse</h2><p className="panel-copy">New connections flagged in the last 24 hours</p></div><span className="mono accent" style={{ fontSize: 10 }}>+12.8%</span></div><div className="metric-strip"><div className="metric"><div className="metric-label">New phone links</div><div className="metric-value">14</div></div><div className="metric"><div className="metric-label">Bank accounts traced</div><div className="metric-value">08</div></div><div className="metric"><div className="metric-label">Evidence approved</div><div className="metric-value green">21</div></div></div></section>
      </div>
    </div>
  );
}

function CasesView({ selectedId, onSelect }: { selectedId: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => cases.filter((item) => `${item.id} ${item.title} ${item.summary} ${item.suspects.join(' ')}`.toLowerCase().includes(query.toLowerCase())), [query]);
  return <div className="page"><div className="page-header"><div><div className="eyebrow">Evidence registry / secure index</div><h1 className="page-title">Cases / Investigations</h1><p className="page-subtitle">{filtered.length} records available to officer-4402 · select an investigation to review</p></div><button className="button-secondary" data-testid="button-filter-cases"><BarChart3 size={14} style={{ verticalAlign: 'middle', marginRight: 5 }} /> Filter view</button></div><div className="searchbar"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search case ID, investigation, suspect or summary..." data-testid="input-case-search" /></div>{filtered.length ? <div className="cases-grid">{filtered.map((item) => <button className={`panel case-card ${selectedId === item.id ? 'selected' : ''}`} key={item.id} onClick={() => onSelect(item.id)} data-testid={`card-case-${item.id}`}><div className="case-number">{item.id}</div><h3>{item.title}</h3><div className="case-detail"><span>Status</span><b><StatusBadge status={item.status} /></b></div><div className="case-detail"><span>Key suspects</span><b>{item.suspects.join(' · ')}</b></div><div className="case-card-footer"><span>{item.summary}</span><span className="mono">{item.links} links</span></div></button>)}</div> : <div className="panel" style={{ padding: 40, textAlign: 'center' }}><Search className="muted" /><h3>No matching investigations</h3><p className="muted" style={{ fontSize: 12 }}>Try a case ID, suspect name or entity type.</p></div>}</div>;
}

function Graph({ selectedNode, setSelectedNode, selectedRelationship, onSelectRelationship }: { selectedNode: string | null; setSelectedNode: (id: string | null) => void; selectedRelationship: RelationshipKey; onSelectRelationship: (relationship: RelationshipKey) => void }) {
  const nodeMap = Object.fromEntries(graphNodes.map((node) => [node.id, node]));
  const [zoom, setZoom] = useState(1);
  const zoomIn = () => setZoom((z) => Math.min(z + 0.2, 2));
  const zoomOut = () => setZoom((z) => Math.max(z - 0.2, 0.5));
  const resetView = () => { setZoom(1); setSelectedNode(null); };
  const viewWidth = 650 / zoom;
  const viewHeight = 480 / zoom;
  const graphViewBox = `${325 - viewWidth / 2} ${240 - viewHeight / 2} ${viewWidth} ${viewHeight}`;
  return <div className="panel graph-panel"><div className="graph-toolbar"><button className="graph-tool" data-testid="button-graph-zoom-in" onClick={zoomIn} title="Zoom in"><ZoomIn size={15} /></button><button className="graph-tool" data-testid="button-graph-zoom-out" onClick={zoomOut} title="Zoom out"><ZoomOut size={15} /></button><button className="graph-tool" data-testid="button-graph-reset" onClick={resetView} title="Reset view"><CircleDot size={14} /></button></div><div className="graph-stage"><svg className="graph-svg" viewBox={graphViewBox} role="img" aria-label="Relationship graph for Operation Redline">{edges.map(([from, to, label, suspicious]) => { const a = nodeMap[from]; const b = nodeMap[to]; const relationship = label as RelationshipKey; const active = selectedRelationship === relationship; return <g key={`${from}-${to}`} className={`relationship-link ${active ? 'selected' : ''}`} onClick={() => onSelectRelationship(relationship)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectRelationship(relationship); } }} role="button" tabIndex={0} aria-label={`Inspect ${label} relationship`}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="edge-hitbox" /><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={`edge ${suspicious ? 'unreviewed' : ''} ${active ? 'selected' : ''}`} /><text className={`edge-label ${active ? 'selected' : ''}`} x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 7} textAnchor="middle">{label}</text></g>; })}{graphNodes.map((node) => <g className={`node ${selectedNode === node.id ? 'selected' : ''}`} key={node.id} onClick={() => setSelectedNode(node.id)} style={{ color: node.kind === 'suspect' ? '#a13d3d' : node.kind === 'phone' ? '#6f83a0' : '#6b8f5e' }}><circle cx={node.x} cy={node.y} r={node.kind === 'suspect' ? 13 : 11} fill="currentColor" fillOpacity=".88" stroke="rgba(229,242,248,.62)" /><circle cx={node.x} cy={node.y} r={node.kind === 'suspect' ? 21 : 18} fill="none" stroke="currentColor" strokeOpacity=".18" /><text x={node.x} y={node.y + 34}>{node.label}</text></g>)}</svg></div></div>;
}

function Inspector({ relationship, onClose, reviewed, setReviewed }: { relationship: RelationshipKey; onClose: () => void; reviewed: boolean; setReviewed: (value: boolean) => void }) {
  const detail = relationshipDetails[relationship];
  const statusClass = detail.status === 'APPROVED' ? 'status-green' : detail.status === 'UNREVIEWED' ? 'status-red' : 'status-amber';
  return <aside className="inspector"><div className="inspector-header"><div><div className="eyebrow">Evidence inspector</div><span className="mono muted" style={{ fontSize: 10 }}>{detail.id} · SELECTED</span></div><button className="close-button" onClick={onClose} data-testid="button-close-inspector"><X size={17} /></button></div><div className="inspector-body"><div className="eyebrow">Link relationship</div><h3>{detail.title} <span className="confidence">({detail.confidence})</span></h3><div className="evidence-copy"><strong>{detail.source}</strong><br />{detail.summary}</div>{reviewed ? <div className="reviewed" data-testid="status-evidence-reviewed"><Check size={15} style={{ verticalAlign: 'middle', marginRight: 6 }} />Connection reviewed and audit logged.</div> : <><div className={`status-badge ${statusClass}`} style={{ marginBottom: 12 }}><Clock3 size={12} /> {detail.status}</div>{detail.reviewable && <div className="action-row"><button className="button-primary" onClick={() => setReviewed(true)} data-testid="button-approve-evidence"><Check size={14} style={{ verticalAlign: 'middle', marginRight: 5 }} />Approve connection</button><button className="button-danger" onClick={() => setReviewed(true)} data-testid="button-reject-evidence">Reject</button></div>}</>}<div className="data-section"><h4>Evidence timeline</h4><div className="timeline">{detail.timeline.map((event) => <div className="timeline-item" key={`${event.time}-${event.title}`}><span className="timeline-dot" /><div className="timeline-main"><span className="timeline-time mono">{event.time}</span><strong>{event.title}</strong><span>{event.detail}</span></div></div>)}</div></div><div className="data-section"><h4>Call logs</h4>{detail.callLogs.map((entry) => <div className="data-row" key={`${entry.name}-${entry.detail}`}><span>{entry.name}</span><strong>{entry.detail}</strong></div>)}</div><div className="data-section"><h4>Transaction logs</h4>{detail.transactionLogs.map((entry) => <div className="data-row" key={`${entry.name}-${entry.detail}`}><span>{entry.name}</span><strong>{entry.detail}</strong></div>)}</div></div></aside>;
}

function CaseView({ showInspector, setShowInspector, onOpenInspectorTab, onCloseInspectorTab }: { showInspector: boolean; setShowInspector: (show: boolean) => void; onOpenInspectorTab: () => void; onCloseInspectorTab: () => void }) {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedRelationship, setSelectedRelationship] = useState<RelationshipKey>('SUSPICIOUS_TRANSFER');
  const [reviewedRelationship, setReviewedRelationship] = useState<RelationshipKey | null>(null);
  const openInspectorFor = (relationship: RelationshipKey) => {
    setSelectedRelationship(relationship);
    onOpenInspectorTab();
    setShowInspector(true);
  };
  const closeInspector = () => {
    setShowInspector(false);
    onCloseInspectorTab();
  };
  const relationshipForNode = (nodeId: string): RelationshipKey => {
    const edge = edges.find(([from, to]) => from === nodeId || to === nodeId);
    return (edge ? edge[2] : 'FREQUENT_CALLS') as RelationshipKey;
  };
  return <div className="page"><div className="page-header"><div><div className="eyebrow">Active investigation / evidence review</div><h1 className="page-title">CAS-2026-102 · Operation Redline</h1><p className="page-subtitle">Financial fraud context · Last synchronized 2 minutes ago</p></div><div style={{ display: 'flex', gap: 8 }}><span className="status-badge status-amber">PRIORITIZED</span>{showInspector && <button className="button-danger" onClick={closeInspector} data-testid="button-exit-inspector"><X size={13} style={{ verticalAlign: 'middle', marginRight: 4 }} />Exit review</button>}</div></div><div className="case-detail-layout"><div className="full"><div className="panel"><div className="panel-header"><div><h2 className="panel-title">Case overview metrics</h2><p className="panel-copy">Entity counts and suspicious activity in the current scope</p></div><span className="mono amber" style={{ fontSize: 10 }}>3 UNREVIEWED LINKS</span></div><div className="metric-strip"><div className="metric"><div className="metric-label">Total suspects</div><div className="metric-value">05</div></div><div className="metric"><div className="metric-label">Total phone numbers</div><div className="metric-value">14</div></div><div className="metric"><div className="metric-label">Total bank accounts</div><div className="metric-value">08</div></div></div></div></div><div className="panel" style={{ position: 'relative', minHeight: 480 }}><Graph selectedNode={selectedNode} setSelectedNode={(id) => { setSelectedNode(id); if (id) openInspectorFor(relationshipForNode(id)); }} selectedRelationship={selectedRelationship} onSelectRelationship={openInspectorFor} />{showInspector && <Inspector relationship={selectedRelationship} onClose={closeInspector} reviewed={reviewedRelationship === selectedRelationship} setReviewed={(value) => setReviewedRelationship(value ? selectedRelationship : null)} />}</div><div className="case-side"><div className="approval-alert"><AlertTriangle size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />ALERT: 3 unreviewed links require officer approval.</div><div className="panel person-card"><div className="eyebrow">Primary person of interest</div><h3>Suresh Sharma</h3><div className="person-score amber">72 <span className="muted" style={{ fontSize: 11 }}>suspicion score</span></div><div className="progress-track"><div className="progress-value" style={{ width: '72%' }} /></div><div className="data-row"><span>Phone numbers</span><strong>06 linked</strong></div><div className="data-row"><span>Known associates</span><strong>11 entities</strong></div><div className="data-row"><span>Last activity</span><strong>11 min ago</strong></div><button className="button-secondary button-wide" style={{ marginTop: 12 }} onClick={() => openInspectorFor('SUSPICIOUS_TRANSFER')} data-testid="button-review-evidence-suresh"><FileSearch size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />Open evidence inspector</button></div><div className="panel person-card"><div className="eyebrow">Secondary subject</div><h3>Ramesh Kumar</h3><div className="data-row"><span>Suspicious activity</span><strong className="amber">11 events</strong></div><div className="data-row"><span>Relationship</span><strong>Partner / phone owner</strong></div><button className="button-secondary button-wide" style={{ marginTop: 12 }} onClick={() => openInspectorFor('PARTNER_REL')} data-testid="button-review-evidence-ramesh"><FileSearch size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />Open evidence inspector</button></div></div></div></div>;
}

function Terminated({ onReturn }: { onReturn: () => void }) {
  return <main className="terminated"><div className="terminated-card"><div className="lock-ring"><LockKeyhole size={64} strokeWidth={1.2} /></div><h1>Session terminated</h1><p>Secure context closed · logging audit complete</p><div className="panel summary-card"><h3>Session summary</h3><div className="summary-line"><span>Total session time</span><strong>00h 18m</strong></div><div className="summary-line"><span>Actions audited</span><strong>3 links reviewed</strong></div><div className="summary-line"><span>Case updates</span><strong>1 case updated</strong></div></div><button className="button-secondary" onClick={onReturn} data-testid="button-return-login"><ArrowLeft size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />Return to login</button></div></main>;
}

function Console({ onLogout }: { onLogout: () => void }) {
  const [view, setView] = useState<View>('dashboard');
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectedCase, setSelectedCase] = useState('CAS-2026-102');
  const [inspector, setInspector] = useState(false);
  const navigate = (next: View) => { setView(next); setMenuOpen(false); if (next === 'case') setInspector(true); };
  const openCase = () => { setSelectedCase('CAS-2026-102'); setView('case'); };
  return <div className="console"><Sidebar view={view} setView={navigate} open={menuOpen} onLogout={onLogout} /><div className="workspace"><Topbar view={view} onMenu={() => setMenuOpen(!menuOpen)} onLogout={onLogout} />{view === 'dashboard' && <Dashboard openCase={openCase} />}{view === 'cases' && <CasesView selectedId={selectedCase} onSelect={(id) => { setSelectedCase(id); setView('case'); }} />}{(view === 'case' || view === 'graph') && <CaseView showInspector={inspector} setShowInspector={setInspector} onOpenInspectorTab={() => setView('case')} onCloseInspectorTab={() => setView('graph')} />}</div></div>;
}

function App() {
  const [screen, setScreen] = useState<Screen>('auth');
  if (screen === 'auth') return <AuthScreen onAuthorize={() => setScreen('console')} />;
  if (screen === 'terminated') return <Terminated onReturn={() => setScreen('auth')} />;
  return <Console onLogout={() => setScreen('terminated')} />;
}

export default App;