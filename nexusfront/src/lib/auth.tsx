import { createContext, useContext, useState, type ReactNode } from 'react';

export type Auth = { badge: string; role: string; activeCase: string; token: string };

const Ctx = createContext<{ auth: Auth | null; setAuth: (a: Auth | null) => void }>({
  auth: null, setAuth: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuthState] = useState<Auth | null>(() => {
    try {
      const raw = localStorage.getItem('nexus_auth');
      return raw ? (JSON.parse(raw) as Auth) : null;
    } catch { return null; }
  });
  const setAuth = (a: Auth | null) => {
    setAuthState(a);
    if (a) localStorage.setItem('nexus_auth', JSON.stringify(a));
    else {
      localStorage.removeItem('nexus_auth');
      localStorage.removeItem('nexus_token');
    }
    if (a?.token) localStorage.setItem('nexus_token', a.token);
  };
  return <Ctx.Provider value={{ auth, setAuth }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
