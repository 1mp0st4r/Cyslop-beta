import { useState } from 'react';
import { useLocation } from 'wouter';
import { Fingerprint, KeyRound, ShieldCheck, ChevronRight, LockKeyhole } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';

export default function Login() {
  const [, nav] = useLocation();
  const { setAuth } = useAuth();
  const [badge, setBadge] = useState('OFFICER-4402');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const m = useMutation({
    mutationFn: () => api.login(badge.trim(), password),
    onSuccess: (d) => {
      setAuth({ badge: d.badge_id, role: d.assigned_role, activeCase: d.active_case, token: d.access_token });
      nav('/dashboard');
    },
    onError: (e: Error) => setError(e.message),
  });
  const authorize = () => {
    if (!badge.trim() || password.length < 4) {
      setError('Enter a valid badge ID and access key (min 4 chars) to continue.');
      return;
    }
    setError('');
    m.mutate();
  };
  return (
    <main className="auth-page">
      <section className="auth-card" data-testid="auth-card">
        <div className="brand-block">
          <img src="/logo-full.png" alt="NEXUS Forensics" className="brand-logo-full" />
          <div className="mvp-chip">SIH26189 MVP</div>
        </div>
        <div className="auth-orbit"><LockKeyhole className="auth-lock" size={44} strokeWidth={1.2} /></div>
        <h1 className="auth-title">NEXUS · Secure Access</h1>
        <p className="auth-copy">Restricted investigation workstation. JWT-secured session — every action is logged against your officer identity.</p>
        {error && <div className="auth-error" data-testid="status-auth-error">{error}</div>}
        <label className="field-label" htmlFor="badge">Officer badge ID</label>
        <div className="input-wrap">
          <Fingerprint size={16} />
          <input id="badge" className="text-input" value={badge} onChange={(e) => setBadge(e.target.value)} placeholder="OFFICER-4402" data-testid="input-badge" />
        </div>
        <label className="field-label" htmlFor="password">Access key</label>
        <div className="input-wrap">
          <KeyRound size={16} />
          <input id="password" type="password" className="text-input" value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && authorize()}
            placeholder="Enter secure access key" data-testid="input-password" />
        </div>
        <button className="button-primary button-wide" onClick={authorize} disabled={m.isPending} data-testid="button-authorize">
          {m.isPending ? 'AUTHORIZING…' : <>AUTHORIZE ACCESS <ChevronRight size={15} style={{ verticalAlign: 'middle' }} /></>}
        </button>
        <p className="auth-foot"><ShieldCheck size={13} style={{ verticalAlign: 'middle', marginRight: 5 }} />MHA Internal System · JWT + Audit logging enabled</p>
      </section>
    </main>
  );
}
