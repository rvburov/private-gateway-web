import { useEffect, type ReactNode } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router';
import { errorText } from '../api/errors';
import { AuthPage } from '../auth/AuthPage';
import { AccountLayout, DevicesPage, DownloadLogPage, DownloadsPage, InvitesPage, MembersPage } from '../account';
import { LandingPage } from '../landing/LandingPage';
import { landingText } from '../landing/locales';
import { Brand, Icon, LanguageSwitch, ThemeButton } from '../ui';
import { useApp } from './context';

function Header() {
  const { lang, user } = useApp();
  const text = landingText[lang];
  return <header id="site-header"><div className="header-inner"><Brand /><nav className="header-links" aria-label={text.home}><div className="header-actions"><ThemeButton /><LanguageSwitch /><Link className="btn sign-in-btn" to={user ? '/downloads' : '/login'}><Icon name="user" /><span>{user ? text.account : text.signIn}</span></Link></div></nav></div></header>;
}

export function RequireSession({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { lang, user, loading, sessionError, reloadUser } = useApp();
  const text = landingText[lang];
  if (loading) return <div className="page-status" role="status">{text.loading}</div>;
  if (sessionError) return <div className="page-status"><p role="alert">{errorText(sessionError, lang)}</p><button className="btn" onClick={() => void reloadUser()}>{text.retry}</button></div>;
  if (!user || user.status !== 'active') return <Navigate to="/login" replace />;
  if (admin && user.role !== 'admin') return <Navigate to="/downloads" replace />;
  return children;
}

export function App() {
  const location = useLocation();
  const { lang } = useApp();
  const text = landingText[lang];
  const auth = ['/login', '/register', '/reset'].includes(location.pathname);
  useEffect(() => {
    document.body.classList.toggle('is-auth', auth);
    document.title = 'Private Gateway Web';
    window.scrollTo({ top: 0 });
    return () => { document.body.classList.remove('is-auth'); };
  }, [auth, location.pathname]);
  return <>{!auth && <Header />}<div id="app"><Routes>
    <Route path="/" element={<LandingPage />} />
    <Route path="/login" element={<AuthPage />} />
    <Route path="/register" element={<AuthPage />} />
    <Route path="/reset" element={<AuthPage />} />
    <Route path="/downloads" element={<RequireSession><AccountLayout><DownloadsPage /></AccountLayout></RequireSession>} />
    <Route path="/admin/members" element={<RequireSession admin><AccountLayout><MembersPage /></AccountLayout></RequireSession>} />
    <Route path="/admin/invites" element={<RequireSession admin><AccountLayout><InvitesPage /></AccountLayout></RequireSession>} />
    <Route path="/admin/downloads" element={<RequireSession admin><AccountLayout><DownloadLogPage /></AccountLayout></RequireSession>} />
    <Route path="/devices" element={<RequireSession><AccountLayout><DevicesPage /></AccountLayout></RequireSession>} />
    <Route path="*" element={<section className="page-status"><h1>{text.noPage}</h1><Link to="/">{text.backHome}</Link></section>} />
  </Routes></div></>;
}
