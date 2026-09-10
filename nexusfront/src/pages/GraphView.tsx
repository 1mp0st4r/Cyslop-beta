import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ZoomIn, ZoomOut, CircleDot, X, ShieldAlert } from 'lucide-react';
import { api, ACTIVE_CASE, type GraphEdge, type EntityNode } from '@/lib/api';
import { useAuth } from '@/lib/auth';

function layout(nodes: EntityNode[]) {
  const cx = 325, cy = 240, rx = 230, ry = 165;
  const pos: Record<string, { x: number; y: number }> = {};
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(nodes.length, 1) - Math.PI / 2;
    pos[n.id] = { x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a) };
  });
  return pos;
}

function riskColor(score: number) {
  if (score >= 70) return '#a13d3d';
  if (score >= 40) return '#c98a3d';
  return '#6b8f5e';
}

export default function GraphView() {
  const { auth } = useAuth();
  const caseId = auth?.activeCase || ACTIVE_CASE;
  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<GraphEdge | null>(null);
  const [zoom, setZoom] = useState(1);

  const g = useQuery({ queryKey: ['graph', caseId], queryFn: () => api.graph(caseId) });
  const nodes = useMemo(() => g.data?.nodes || [], [g.data]);
  const edges = useMemo(() => g.data?.edges || [], [g.data]);
  const pos = useMemo(() => layout(nodes), [nodes]);

  // Batch-fetch risk for PERSON nodes so color/size reflect live threat scores.
  const risks = useQuery({
    queryKey: ['risks', caseId, nodes.map((n) => n.id).join(',')],
    enabled: nodes.length > 0,
    queryFn: async () => {
      const out: Record<string, number> = {};
      try { const r = await api.batchRisks(nodes.map((n) => n.id), caseId); for (const n of nodes) out[n.id] = r.risks[n.id]?.threat_score ?? n.base_risk_score; } catch { for (const n of nodes) out[n.id] = n.base_risk_score; }
      return out;
    },
  });
  const selRisk = useQuery({
    queryKey: ['risk', selNode],
    enabled: !!selNode,
    queryFn: () => api.risk(selNode as string),
  });

  const vw = 650 / zoom, vh = 480 / zoom;
  const vb = `${325 - vw / 2} ${240 - vh / 2} ${vw} ${vh}`;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">Core screen · {caseId}</div>
          <h1 className="page-title">Network graph</h1>
          <p className="page-subtitle">Nodes sized/colored by live risk score · click node for RiskAssessment, edge for evidence_source</p>
        </div>
        <span className="status-badge status-amber">{edges.filter((e) => e.status?.toUpperCase().includes('PEND')).length} PENDING EDGES</span>
      </div>
      {g.isError && <div className="auth-error">Graph load failed: {(g.error as Error).message}</div>}
      <div className="panel graph-panel" style={{ minHeight: 520 }}>
        <div className="graph-toolbar">
          <button className="graph-tool" onClick={() => setZoom((z) => Math.min(z + 0.2, 2))} title="Zoom in"><ZoomIn size={15} /></button>
          <button className="graph-tool" onClick={() => setZoom((z) => Math.max(z - 0.2, 0.5))} title="Zoom out"><ZoomOut size={15} /></button>
          <button className="graph-tool" onClick={() => { setZoom(1); setSelNode(null); setSelEdge(null); }} title="Reset"><CircleDot size={14} /></button>
        </div>
        <div className="graph-stage">
          <svg className="graph-svg" viewBox={vb} role="img" aria-label="Case network graph" style={{ minHeight: 520 }}>
            {edges.map((e) => {
              const a = pos[e.source_id]; const b = pos[e.target_id];
              if (!a || !b) return null;
              const pend = e.status?.toUpperCase().includes('PEND') || e.status?.toUpperCase().includes('UNREV');
              const active = selEdge?.link_id === e.link_id;
              return (
                <g key={e.link_id} className="relationship-link" role="button" tabIndex={0}
                  onClick={() => { setSelEdge(e); }}
                  onKeyDown={(ev) => { if (ev.key === 'Enter') setSelEdge(e); }}
                  aria-label={`Inspect ${e.relation_type}`}>
                  <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="edge-hitbox" />
                  <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={`edge ${pend ? 'unreviewed' : ''} ${active ? 'selected' : ''}`} />
                  <text className={`edge-label ${active ? 'selected' : ''}`} x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 7} textAnchor="middle">
                    {e.relation_type} · {Math.round(e.confidence_score * 100)}%
                  </text>
                </g>
              );
            })}
            {nodes.map((n) => {
              const p = pos[n.id]; if (!p) return null;
              const score = risks.data?.[n.id] ?? n.base_risk_score ?? 10;
              const c = riskColor(score);
              const r = 9 + Math.min(score / 100, 1) * 10;
              return (
                <g key={n.id} className={`node ${selNode === n.id ? 'selected' : ''}`}
                  style={{ color: c }} onClick={() => { setSelNode(n.id); setSelEdge(null); }}>
                  <circle cx={p.x} cy={p.y} r={r} fill="currentColor" fillOpacity=".88" stroke="rgba(229,242,248,.62)" />
                  <circle cx={p.x} cy={p.y} r={r + 8} fill="none" stroke="currentColor" strokeOpacity=".18" />
                  <text x={p.x} y={p.y + r + 16}>{n.name} ({Math.round(score)})</text>
                </g>
              );
            })}
          </svg>
        </div>
        {(selNode || selEdge) && (
          <aside className="inspector">
            <div className="inspector-header">
              <div><div className="eyebrow">Evidence inspector</div><span className="mono muted" style={{ fontSize: 10 }}>{selNode || selEdge?.link_id} · SELECTED</span></div>
              <button className="close-button" onClick={() => { setSelNode(null); setSelEdge(null); }}><X size={17} /></button>
            </div>
            <div className="inspector-body">
              {selNode && (
                <>
                  <div className="eyebrow">RiskAssessment · ISO 27005</div>
                  {selRisk.isPending && <p className="muted" style={{ fontSize: 12 }}>Scoring…</p>}
                  {selRisk.isError && <div className="auth-error">{(selRisk.error as Error).message}</div>}
                  {selRisk.data && (
                    <>
                      <h3>{nodes.find((n) => n.id === selNode)?.name} <span className="confidence">({selRisk.data.threat_score}/100 · {selRisk.data.risk_level})</span></h3>
                      <div className="progress-track"><div className="progress-value" style={{ width: `${selRisk.data.threat_score}%` }} /></div>
                      <div className="data-section"><h4>Contributing factors</h4>
                        {selRisk.data.contributing_factors.map((f) => <div className="data-row" key={f}><span><ShieldAlert size={11} style={{ verticalAlign: 'middle', marginRight: 6 }} />{f}</span></div>)}
                      </div>
                    </>
                  )}
                </>
              )}
              {selEdge && !selNode && (
                <>
                  <div className="eyebrow">Edge · {selEdge.link_id}</div>
                  <h3>{selEdge.relation_type} <span className="confidence">({Math.round(selEdge.confidence_score * 100)}% confidence)</span></h3>
                  <div className={`status-badge ${selEdge.status?.toUpperCase().includes('APPROV') ? 'status-green' : 'status-amber'}`}>{selEdge.status}</div>
                  <div className="evidence-copy"><strong>evidence_source</strong><br />{selEdge.evidence_source}</div>
                  <div className="data-row"><span>Source</span><strong>{selEdge.source_id}</strong></div>
                  <div className="data-row"><span>Target</span><strong>{selEdge.target_id}</strong></div>
                </>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
