import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError, request } from '../api/client';
import type { User } from '../api/types';
export type { User } from '../api/types';

export type Language = 'en' | 'ru';
interface AppContext {
  lang: Language;
  setLanguage: (lang: Language) => void;
  theme: 'light' | 'dark';
  toggleTheme: () => void;
  user: User | null;
  setUser: (user: User | null) => void;
  loading: boolean;
  sessionError: unknown;
  reloadUser: () => Promise<User | null>;
}

const Context = createContext<AppContext | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [lang, setLanguage] = useState<Language>('en');
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessionError, setSessionError] = useState<unknown>(null);
  const sessionRevision = useRef(0);
  const setUser = useCallback((value: User | null) => {
    sessionRevision.current += 1;
    setUserState(value);
    setLoading(false);
    setSessionError(null);
  }, []);
  const reloadUser = useCallback(async () => {
    const revision = ++sessionRevision.current;
    setLoading(true);
    setSessionError(null);
    try {
      const value = await request<User>('/api/me');
      if (revision !== sessionRevision.current) return null;
      setUserState(value);
      return value;
    } catch (error) {
      if (revision !== sessionRevision.current) return null;
      setUserState(null);
      if (!(error instanceof ApiError && error.status === 401)) setSessionError(error);
      return null;
    } finally { if (revision === sessionRevision.current) setLoading(false); }
  }, []);
  useEffect(() => { void reloadUser(); return () => { sessionRevision.current += 1; }; }, [reloadUser]);
  useEffect(() => {
    const expired = () => setUser(null);
    window.addEventListener('pg-session-expired', expired);
    return () => window.removeEventListener('pg-session-expired', expired);
  }, [setUser]);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const toggleTheme = useCallback(() => setTheme(value => value === 'light' ? 'dark' : 'light'), []);
  const value = useMemo(() => ({ lang, setLanguage, theme, toggleTheme, user, setUser, loading, sessionError, reloadUser }),
    [lang, theme, toggleTheme, user, setUser, loading, sessionError, reloadUser]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useApp(): AppContext {
  const value = useContext(Context);
  if (!value) throw new Error('AppProvider is missing');
  return value;
}
