import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { NavLink, useNavigate, useSearchParams } from 'react-router';
import { request } from '../api/client';
import { errorText } from '../api/errors';
import { useApp } from '../app/context';
import { Icon } from '../ui';
import { accountText } from './locales';
import { cardOrder, detectPlatform } from './platform';
import { inviteStatus, looksLikeEmail, personName, safeDownloadUrl, type DevicesInfo, type Download, type DownloadEvent, type Invite, type InviteStatus, type ListResult, type Platform, type User } from './types';
import './account.css';

const PAGE_SIZE = 20;

function useAccountText() {
  const { lang } = useApp();
  return accountText[lang];
}

function useResource<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [dataPath, setDataPath] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    request<T>(path).then((result) => {
      if (active) { setData(result); setDataPath(path); setLoading(false); }
    }).catch((reason: unknown) => {
      if (active) { setError(reason); setLoading(false); }
    });
    return () => { active = false; };
  }, [path, revision]);
  // fresh: данные относятся к текущему адресу, а не к прежнему фильтру или странице
  return { data, error, loading, reload, fresh: dataPath === path };
}

function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  const { lang } = useApp();
  const text = useAccountText();
  if (!error) return null;
  return <div className="ac-api-error" role="alert"><p>{errorText(error, lang)}</p>{retry && <button className="btn" onClick={retry}>{text.retry}</button>}</div>;
}

function Loading() {
  const text = useAccountText();
  return <p className="ac-loading" role="status">{text.loading}</p>;
}

function Heading({ kicker, title, description, action }: { kicker: string; title: string; description: string; action?: ReactNode }) {
  return <div className="ac-heading"><div><span className="eyebrow">{kicker}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

export function AccountLayout({ children }: { children: ReactNode }) {
  const text = useAccountText();
  const { user, setUser } = useApp();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function logout() {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      await request('/api/auth/logout', { method: 'POST', body: {} });
      setUser(null);
      navigate('/login', { replace: true });
    } catch (reason) { setError(reason); }
    finally { setBusy(false); }
  }
  const navClass = ({ isActive }: { isActive: boolean }) => `ac-nav-link ${isActive ? 'is-active' : ''}`;
  return <section className="ac-shell" id="pg-account">
    <aside className="ac-sidebar">
      <div className="ac-sidebar-head"><span className="eyebrow">PRIVATE GATEWAY WEB</span><h2>{text.account}</h2></div>
      <nav aria-label={text.account}>
        <NavLink to="/downloads" className={navClass}><Icon name="download" /><span>{text.downloadNav}</span></NavLink>
        <NavLink to="/devices" className={navClass}><Icon name="monitor" /><span>{text.devicesNav}</span></NavLink>
        {user?.role === 'admin' && <><div className="ac-nav-caption">{text.admin}</div>
          <NavLink to="/admin/members" className={navClass}><Icon name="users" /><span>{text.members}</span></NavLink>
          <NavLink to="/admin/invites" className={navClass}><Icon name="mail" /><span>{text.invites}</span></NavLink>
          <NavLink to="/admin/downloads" className={navClass}><Icon name="history" /><span>{text.downloadLog}</span></NavLink>
        </>}
      </nav>
      <div className="ac-sidebar-bottom">
        <div className="ac-session"><span className="ac-avatar small"><Icon name="user" /></span><div><strong>{user ? personName(user) : ''}</strong><span>{user?.role === 'admin' ? text.roleAdmin : text.roleMember}</span></div></div>
        <button className="ac-nav-link ac-logout" disabled={busy} onClick={() => void logout()}><Icon name="logout" /><span>{busy ? text.working : text.logout}</span></button>
        <ErrorNotice error={error} />
      </div>
    </aside>
    <main className="ac-main">{children}</main>
  </section>;
}

const platformNames: Record<Platform, string> = { windows: 'Windows', macos: 'macOS', ios: 'iOS', linux: 'Linux', android: 'Android' };
const platformIcons = { windows: 'windows', macos: 'apple', ios: 'apple', linux: 'linux', android: 'android' } as const;

export function DownloadsPage() {
  const { lang } = useApp();
  const text = useAccountText();
  const resource = useResource<{ items: Download[] }>('/api/downloads');
  // Система посетителя: ее карточка первая и с основной кнопкой; неизвестная — Windows, как раньше
  const detected = useMemo(() => detectPlatform(typeof navigator === 'undefined' ? undefined : navigator), []);
  const featured: Platform = detected ?? 'windows';
  const featuredTag = detected ? text.yourSystem : text.desktop;
  const find = (platform: Platform): Download => resource.data?.items.find((item) => item.platform === platform) ?? {
    platform, available: false, version: null, filename: null, size_bytes: null, sha256: null, url: null,
  };
  const ios = find('ios');
  const iosUrl = safeDownloadUrl(ios);
  const iosFirst = featured === 'ios';
  const iosCard = <div className={`ac-ios card ${iosFirst ? 'is-featured is-first' : ''}`} data-platform="ios"><div className="ac-os-icon"><Icon name="apple" /></div><div><h3>{text.iosTitle}{iosFirst && <span className="ac-tag">{featuredTag}</span>}</h3><p>{text.iosLead}</p></div>
    {iosUrl ? <a className={`btn ${iosFirst ? 'primary' : ''}`} href={iosUrl} target="_blank" rel="noopener noreferrer">{text.appStore}</a> : <span className="ac-status is-muted">{text.appStorePending}</span>}
  </div>;
  return <>
    <Heading kicker={text.application} title={text.downloadsTitle} description={text.downloadsLead} />
    <div className="ac-download-banner"><div className="ac-banner-icon"><Icon name="shield" /></div><div><strong>{text.bannerTitle}</strong><p>{text.bannerLead}</p></div></div>
    {resource.loading ? <Loading /> : resource.error ? <ErrorNotice error={resource.error} retry={resource.reload} /> : <>
      {iosFirst && iosCard}
      <div className="ac-download-grid">{cardOrder(detected).map((platform) => {
        const item = find(platform), url = safeDownloadUrl(item), isFeatured = platform === featured;
        const descriptions = { windows: text.windowsLead, macos: text.macosLead, linux: text.linuxLead, android: text.androidLead, ios: text.iosLead };
        return <article key={platform} className={`ac-download-card ${isFeatured ? 'is-featured' : ''}`} data-platform={platform}>
          <div className="ac-os-icon"><Icon name={platformIcons[platform]} /></div>
          <div className="ac-download-title"><h2>{platformNames[platform]}</h2>{isFeatured && <span className="ac-tag">{featuredTag}</span>}</div>
          <p>{descriptions[platform]}</p><div className="ac-platform-space" />
          {url ? <a className={`btn ${isFeatured ? 'primary' : ''} ac-download-btn`} href={url} download><Icon name="download" />{text.download} {platformNames[platform]}</a>
            : <button className="btn ac-download-btn" disabled><Icon name="download" />{text.unavailable}</button>}
          <div className="ac-file-label">{url ? <>{item.version && <span>{text.version} {item.version}</span>}{item.filename && <span>{item.filename}</span>}{item.size_bytes !== null && <span>{new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(item.size_bytes / 1024 / 1024)} MB</span>}</> : text.unavailable}</div>
          {platform === 'android' && <p className="ac-install-hint"><Icon name="info" /><span>{text.androidHint}</span></p>}
          {url && item.sha256 && <details className="ac-checksum"><summary>{text.checksum}</summary><code>{item.sha256}</code></details>}
        </article>;
      })}</div>
      {!iosFirst && iosCard}
      <div className="ac-download-foot"><Icon name="lock" /><p>{text.fileNote}</p></div>
    </>}
  </>;
}

function Pagination({ total, offset, onChange, busy }: { total: number; offset: number; onChange: (offset: number) => void; busy: boolean }) {
  const text = useAccountText();
  if (total <= PAGE_SIZE) return null;
  return <nav className="ac-pagination" aria-label={`${text.page} ${Math.floor(offset / PAGE_SIZE) + 1}`}>
    <button className="btn" disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}>{text.previous}</button>
    <span>{text.page} {Math.floor(offset / PAGE_SIZE) + 1} {text.of} {Math.max(1, Math.ceil(total / PAGE_SIZE))}</span>
    <button className="btn" disabled={busy || offset + PAGE_SIZE >= total} onClick={() => onChange(offset + PAGE_SIZE)}>{text.next}</button>
  </nav>;
}

function AccessBadge({ active }: { active: boolean }) {
  const text = useAccountText();
  return <span className={`ac-status ${active ? 'is-good' : 'is-muted'}`}><i />{active ? text.activeBadge : text.blockedBadge}</span>;
}
function InviteBadge({ status }: { status: InviteStatus }) {
  const text = useAccountText();
  const labels = { active: text.inviteActive, used: text.inviteUsed, revoked: text.inviteRevoked, expired: text.inviteExpired };
  return <span className={`ac-status ${status === 'active' ? 'is-good' : 'is-muted'}`}><i />{labels[status]}</span>;
}
// 2FA бывает только у администратора; участник входит по паролю (DECISIONS п. 11)
function Protection({ user }: { user: User }) {
  const text = useAccountText();
  if (user.role !== 'admin') return <span className="ac-2fa is-password"><Icon name="lock" />{text.passwordOnly}</span>;
  return <span className={`ac-2fa ${user.totp_enabled ? '' : 'is-off'}`}><Icon name={user.totp_enabled ? 'shield' : 'key'} />{user.totp_enabled ? text.twoFactorOn : text.twoFactorOff}</span>;
}
function Person({ user, onClick }: { user: User; onClick?: () => void }) {
  const name = personName(user);
  return <div className="ac-person"><span className="ac-avatar">{name.split(/\s+/).map((part) => part[0]).slice(0, 2).join('')}</span><div>{onClick ? <button className="ac-name-link" onClick={onClick}>{name}</button> : <strong>{name}</strong>}<span>{user.email}</span></div></div>;
}
function daysText(days: number, lang: 'en' | 'ru') {
  if (lang === 'en') return days === 1 ? '1 day' : `${days} days`;
  const form = new Intl.PluralRules('ru').select(days);
  return `${days} ${form === 'one' ? 'день' : form === 'few' ? 'дня' : 'дней'}`;
}
function dateLabel(value: string, lang: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function Dialog({ title, children, footer, close, busy = false }: { title: string; children: ReactNode; footer?: ReactNode; close: () => void; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const text = useAccountText();
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (typeof element.showModal === 'function') element.showModal();
    else element.setAttribute('open', '');
    return () => { if (typeof element.close === 'function') element.close(); };
  }, []);
  return <dialog className="ac-dialog" ref={ref} aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); if (!busy) close(); }}>
    <div className="ac-dialog-head"><div><span className="eyebrow">PRIVATE GATEWAY WEB</span><h2 id={titleId}>{title}</h2></div><button className="ac-close" onClick={close} disabled={busy} aria-label={text.close}><Icon name="close" /></button></div>
    <div className="ac-dialog-body">{children}</div>{footer && <div className="ac-dialog-footer">{footer}</div>}
  </dialog>;
}

function OtpField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const text = useAccountText();
  const id = useId();
  return <><label className="ac-field" htmlFor={id}>{text.otp}<input id={id} value={value} onChange={(event) => onChange(event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" required pattern="[0-9]{6}" minLength={6} maxLength={6} aria-describedby={`${id}-hint`} /></label><p className="ac-otp-hint" id={`${id}-hint`}>{text.otpHint}</p></>;
}

interface SecretResult { title: string; recipient: string; code: string; expires_at: string }
function SecretDialog({ result, close }: { result: SecretResult; close: () => void }) {
  const text = useAccountText();
  const { lang } = useApp();
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'manual'>('idle');
  const ref = useRef<HTMLInputElement>(null);
  async function copy() {
    try { await navigator.clipboard.writeText(result.code); setCopyState('copied'); }
    catch { setCopyState('manual'); ref.current?.focus(); ref.current?.select(); }
  }
  return <Dialog title={result.title} close={close} footer={<button className="btn primary" onClick={close}>{text.done}</button>}>
    <div className="ac-success-mark"><Icon name="check" /></div><p><strong>{result.recipient}</strong></p><p>{text.onceHint}</p>
    <div className="ac-code-box"><input className="ac-secret-input" ref={ref} readOnly value={result.code} aria-label={text.codeLabel} /><button className="btn ghost" onClick={() => void copy()} aria-label={text.copy}><Icon name="copy" /></button></div>
    {copyState !== 'idle' && <p role="status">{copyState === 'copied' ? text.copied : text.copyFallback}</p>}
    <dl className="ac-details"><div><dt>{text.expires}</dt><dd>{dateLabel(result.expires_at, lang)}</dd></div></dl>
  </Dialog>;
}

function InviteDialog({ close, onCreated }: { close: () => void; onCreated: () => void }) {
  const text = useAccountText();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'member' | 'admin'>('member');
  const [days, setDays] = useState(7);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState('');
  const [result, setResult] = useState<SecretResult | null>(null);
  const formId = useId();
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!looksLikeEmail(email.trim())) { setValidation(text.emailInvalid); return; }
    if (!/^\d{6}$/.test(code)) { setValidation(text.otpInvalid); return; }
    setValidation(''); setError(null); setBusy(true);
    try {
      const response = await request<{ invite: Invite; code: string }>('/api/admin/invites', { method: 'POST', body: { email: email.trim().toLowerCase(), role, expires_in_days: days, code } });
      setCode('');
      setResult({ title: text.inviteCreated, recipient: response.invite.email, code: response.code, expires_at: response.invite.expires_at });
      onCreated();
    } catch (reason) { setCode(''); setError(reason); }
    finally { setBusy(false); }
  }
  if (result) return <SecretDialog result={{ ...result, title: text.inviteCreated }} close={close} />;
  return <Dialog title={text.inviteTitle} close={close} busy={busy} footer={<><button className="btn" disabled={busy} onClick={close}>{text.cancel}</button><button className="btn primary" form={formId} type="submit" disabled={busy}>{busy ? text.working : text.createInvite}</button></>}>
    <p>{text.inviteIntro}</p><form id={formId} onSubmit={(event) => void submit(event)} noValidate>
      <label className="ac-field">{text.email}<input type="email" name="email" value={email} onChange={(event) => { setEmail(event.target.value); setValidation(''); }} maxLength={254} autoComplete="off" required /></label>
      <div className="ac-form-grid"><label className="ac-field">{text.role}<select value={role} onChange={(event) => setRole(event.target.value as 'member' | 'admin')}><option value="member">{text.roleMember}</option><option value="admin">{text.roleAdmin}</option></select></label><label className="ac-field">{text.expiry}<select value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={1}>{text.day}</option><option value={3}>{text.threeDays}</option><option value={7}>{text.sevenDays}</option><option value={30}>{text.thirtyDays}</option></select></label></div>
      <div className="ac-role-hint">{role === 'member' ? text.memberHint : text.adminHint}</div><OtpField value={code} onChange={(value) => { setCode(value); setValidation(''); }} />
      {validation && <p className="ac-form-error" role="alert">{validation}</p>}<ErrorNotice error={error} />
    </form>
  </Dialog>;
}

type MemberAction = 'block' | 'restore' | 'promote' | 'demote' | 'reset' | 'limit' | 'delete';
function MemberDialog({ member, close, onChanged }: { member: User; close: () => void; onChanged: () => void }) {
  const text = useAccountText();
  const { user, lang } = useApp();
  const [action, setAction] = useState<MemberAction | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState('');
  const [result, setResult] = useState<SecretResult | null>(null);
  const [limit, setLimit] = useState(member.device_limit ? String(member.device_limit) : '');
  const navigate = useNavigate();
  const formId = useId();
  const limitId = useId();
  const labels = { block: text.revokeAccess, restore: text.restoreAccess, promote: text.promote, demote: text.demote, reset: text.resetCode, limit: text.setLimit, delete: text.deleteMember };
  const descriptions = { block: text.revokeDescription, restore: text.restoreDescription, promote: text.promoteDescription, demote: text.demoteDescription, reset: text.resetDescription, limit: text.limitDescription, delete: text.deleteDescription };
  function choose(next: MemberAction) { setAction(next); setCode(''); setError(null); setValidation(''); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!action || busy) return;
    const limitValue = limit.trim() === '' ? null : Number(limit);
    if (action === 'limit' && limitValue !== null && (!Number.isInteger(limitValue) || limitValue < 1 || limitValue > 50)) { setValidation(text.limitInvalid); return; }
    if (!/^\d{6}$/.test(code)) { setValidation(text.otpInvalid); return; }
    setBusy(true); setError(null); setValidation('');
    try {
      if (action === 'limit') {
        await request(`/api/admin/members/${member.id}`, { method: 'PATCH', body: { device_limit: limitValue, code } });
        onChanged(); close();
      } else if (action === 'delete') {
        await request(`/api/admin/members/${member.id}/delete`, { method: 'POST', body: { code } });
        onChanged(); close();
      } else if (action === 'reset') {
        const response = await request<{ code: string; expires_at: string }>(`/api/admin/members/${member.id}/reset-code`, { method: 'POST', body: { code } });
        setResult({ title: text.resetCreated, recipient: member.email, ...response });
      } else {
        const patch = action === 'block' || action === 'restore' ? { status: action === 'block' ? 'blocked' : 'active' } : { role: action === 'promote' ? 'admin' : 'member' };
        await request(`/api/admin/members/${member.id}`, { method: 'PATCH', body: { ...patch, code } });
        onChanged(); close();
      }
      setCode('');
    } catch (reason) { setCode(''); setError(reason); }
    finally { setBusy(false); }
  }
  if (result) return <SecretDialog result={{ ...result, title: text.resetCreated }} close={close} />;
  return <Dialog title={action ? labels[action] : personName(member)} close={close} busy={busy}
    footer={action ? <><button className="btn" disabled={busy} onClick={() => { setAction(null); setCode(''); setError(null); }}>{text.cancel}</button><button className={`btn ${action === 'block' || action === 'delete' ? 'ac-danger' : 'primary'}`} form={formId} type="submit" disabled={busy}>{busy ? text.working : action === 'delete' ? text.deleteMember : text.confirm}</button></> : <button className="btn" onClick={close}>{text.done}</button>}>
    <Person user={member} /><dl className="ac-details"><div><dt>{text.role}</dt><dd>{member.role === 'admin' ? text.roleAdmin : text.roleMember}</dd></div><div><dt>{text.access}</dt><dd><AccessBadge active={member.status === 'active'} /></dd></div><div><dt>{text.protection}</dt><dd><Protection user={member} /></dd></div><div><dt>{text.created}</dt><dd>{dateLabel(member.created_at, lang)}</dd></div></dl>
    {action ? <form id={formId} noValidate onSubmit={(event) => void submit(event)}><p>{descriptions[action]}</p>{action === 'limit' && <label className="ac-field" htmlFor={limitId}>{text.limitField}<input id={limitId} value={limit} onChange={(event) => { setLimit(event.target.value.replace(/\D/g, '').slice(0, 2)); setValidation(''); }} inputMode="numeric" placeholder={text.defaultLimit} /></label>}<OtpField value={code} onChange={(value) => { setCode(value); setValidation(''); }} />{validation && <p className="ac-form-error" role="alert">{validation}</p>}<ErrorNotice error={error} /></form>
      : <>
        {member.id !== user?.id && <div className="ac-member-actions"><button className="btn" onClick={() => choose(member.status === 'active' ? 'block' : 'restore')}>{member.status === 'active' ? text.revokeAccess : text.restoreAccess}</button><button className="btn" onClick={() => choose(member.role === 'admin' ? 'demote' : 'promote')}>{member.role === 'admin' ? text.demote : text.promote}</button><button className="btn" onClick={() => choose('reset')}>{text.resetCode}</button></div>}
        <div className="ac-member-actions">{member.id !== user?.id && <button className="btn" onClick={() => choose('limit')}>{text.setLimit}</button>}<button className="btn" onClick={() => { close(); navigate(`/admin/downloads?user=${member.id}`); }}><Icon name="history" />{text.memberDownloads}</button></div>
        <MemberDevices memberId={member.id} />
        {member.id !== user?.id && <div className="ac-member-actions ac-member-danger"><button className="btn ac-danger-text" onClick={() => choose('delete')}><Icon name="close" />{text.deleteMember}</button></div>}
      </>}
  </Dialog>;
}

export function MembersPage() {
  const text = useAccountText();
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'active' | 'blocked'>('all');
  const [offset, setOffset] = useState(0);
  const [member, setMember] = useState<User | null>(null);
  const [creating, setCreating] = useState(false);
  const parameters = new URLSearchParams({ q: query, limit: String(PAGE_SIZE), offset: String(offset) });
  if (filter !== 'all') parameters.set('status', filter);
  const resource = useResource<ListResult<User>>(`/api/admin/members?${parameters}`);
  const items = resource.data?.items ?? [];
  return <>
    <Heading kicker={text.admin} title={text.members} description={text.membersLead} action={<button className="btn primary" onClick={() => setCreating(true)}><Icon name="plus" />{text.inviteMember}</button>} />
    {resource.data && <div className="ac-stats"><div className="card"><span>{text.totalMembers}</span><strong>{resource.data.total}</strong></div><div className="card"><span>{text.activePage}</span><strong>{items.filter((item) => item.status === 'active').length}</strong></div><div className="card"><span>{text.adminsPage}</span><strong>{items.filter((item) => item.role === 'admin').length}</strong></div></div>}
    <section className="card ac-members-card">
      <div className="ac-table-toolbar"><form className="ac-search-form" onSubmit={(event) => { event.preventDefault(); setQuery(search.trim()); setOffset(0); }}><label className="ac-search"><Icon name="search" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={text.search} aria-label={text.searchLabel} maxLength={200} /></label><button className="btn ac-small-btn" type="submit">{text.searchButton}</button></form><div className="ac-filter" role="group" aria-label={text.accessFilter}>{(['all', 'active', 'blocked'] as const).map((value) => <button key={value} className={filter === value ? 'selected' : ''} aria-pressed={filter === value} onClick={() => { setFilter(value); setOffset(0); }}>{text[value]}</button>)}</div></div>
      {resource.loading ? <Loading /> : resource.error ? <ErrorNotice error={resource.error} retry={resource.reload} /> : items.length === 0 ? <div className="ac-empty"><Icon name="search" /><h3>{text.memberEmpty}</h3><p>{text.memberEmptyLead}</p></div>
        : <table className="ac-table"><caption className="ac-sr-only">{text.membersLead}</caption><thead><tr><th>{text.member}</th><th>{text.role}</th><th>{text.protection}</th><th>{text.access}</th><th><span className="ac-sr-only">{text.actions}</span></th></tr></thead><tbody>{items.map((item) => <tr key={item.id}>
          <td><Person user={item} onClick={() => setMember(item)} /></td><td data-label={text.role}><span className={`ac-role ${item.role === 'admin' ? 'is-admin' : ''}`}>{item.role === 'admin' ? text.roleAdmin : text.roleMember}</span></td>
          <td data-label={text.protection}><Protection user={item} /></td><td data-label={text.access}><AccessBadge active={item.status === 'active'} /></td><td className="ac-table-action"><button className="btn ghost ac-small-btn" onClick={() => setMember(item)} aria-label={`${text.details}: ${personName(item)}`}>{text.details}<Icon name="chevron" /></button></td>
        </tr>)}</tbody></table>}
    </section>
    {resource.data && <Pagination total={resource.data.total} offset={offset} busy={resource.loading} onChange={setOffset} />}
    <p className="ac-boundary"><Icon name="lock" />{text.accessBoundary}</p>
    {member && <MemberDialog member={member} close={() => setMember(null)} onChanged={resource.reload} />}
    {creating && <InviteDialog close={() => setCreating(false)} onCreated={resource.reload} />}
  </>;
}

function InviteActionDialog({ invite, mode, close, onChanged }: { invite: Invite; mode: 'revoke' | 'delete'; close: () => void; onChanged: () => void }) {
  const text = useAccountText();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState('');
  const formId = useId();
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!/^\d{6}$/.test(code)) { setValidation(text.otpInvalid); return; }
    setBusy(true); setError(null); setValidation('');
    try { await request(`/api/admin/invites/${invite.id}/${mode}`, { method: 'POST', body: { code } }); onChanged(); close(); }
    catch (reason) { setCode(''); setError(reason); }
    finally { setBusy(false); }
  }
  const revoke = mode === 'revoke';
  return <Dialog title={revoke ? text.revokeInviteTitle : text.deleteInviteTitle} busy={busy} close={close} footer={<><button className="btn" disabled={busy} onClick={close}>{text.cancel}</button><button className="btn ac-danger" type="submit" form={formId} disabled={busy}>{busy ? text.working : revoke ? text.revokeInvite : text.deleteInvite}</button></>}>
    <p><strong>{invite.email}</strong></p><p>{revoke ? text.revokeInviteDescription : text.deleteInviteDescription}</p><form id={formId} noValidate onSubmit={(event) => void submit(event)}><OtpField value={code} onChange={(value) => { setCode(value); setValidation(''); }} />{validation && <p className="ac-form-error" role="alert">{validation}</p>}<ErrorNotice error={error} /></form>
  </Dialog>;
}

export function InvitesPage() {
  const text = useAccountText();
  const { lang } = useApp();
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState<'all' | InviteStatus>('all');
  const [creating, setCreating] = useState(false);
  const [acting, setActing] = useState<{ invite: Invite; mode: 'revoke' | 'delete' } | null>(null);
  const resource = useResource<ListResult<Invite>>(`/api/admin/invites?limit=${PAGE_SIZE}&offset=${offset}`);
  const items = resource.data?.items.filter((item) => filter === 'all' || inviteStatus(item) === filter) ?? [];
  return <>
    <Heading kicker={text.admin} title={text.invites} description={text.invitesLead} action={<button className="btn primary" onClick={() => setCreating(true)}><Icon name="plus" />{text.createInvite}</button>} />
    <section className="card ac-invites-card"><div className="ac-invites-head"><div><h2>{text.invitesHeading}</h2><p>{text.invitesSub}</p></div><label className="ac-select-label"><span className="ac-sr-only">{text.inviteFilter}</span><select value={filter} onChange={(event) => setFilter(event.target.value as 'all' | InviteStatus)}><option value="all">{text.allStatuses}</option><option value="active">{text.inviteActive}</option><option value="used">{text.inviteUsed}</option><option value="revoked">{text.inviteRevoked}</option><option value="expired">{text.inviteExpired}</option></select></label></div>
      {resource.loading ? <Loading /> : resource.error ? <ErrorNotice error={resource.error} retry={resource.reload} /> : items.length === 0 ? <div className="ac-empty"><h3>{text.inviteEmpty}</h3><p>{text.inviteEmptyLead}</p></div> : items.map((invite) => {
        const status = inviteStatus(invite);
        return <article className="ac-invite-item" key={invite.id}><span className="ac-invite-icon"><Icon name={status === 'used' ? 'check' : 'mail'} /></span><div className="ac-invite-info"><div><strong>{invite.email}</strong><InviteBadge status={status} /></div><p>{invite.role === 'admin' ? text.roleAdmin : text.roleMember}<span>·</span>{text.expires}: {dateLabel(invite.expires_at, lang)}</p></div><div className="ac-invite-actions">{status === 'active' && <button className="btn ghost ac-small-btn" onClick={() => setActing({ invite, mode: 'revoke' })} aria-label={`${text.revokeInvite}: ${invite.email}`}>{text.revokeInvite}</button>}<button className="btn ghost ac-small-btn" onClick={() => setActing({ invite, mode: 'delete' })} aria-label={`${text.deleteInvite}: ${invite.email}`}>{text.deleteInvite}</button></div></article>;
      })}
    </section>
    {resource.data && <Pagination total={resource.data.total} offset={offset} busy={resource.loading} onChange={setOffset} />}
    <div className="ac-invite-help"><div className="ac-invite-help-icon"><Icon name="link" /></div><div><h3>{text.howTitle}</h3><p>{text.howLead}</p></div></div>
    {creating && <InviteDialog close={() => setCreating(false)} onCreated={resource.reload} />}
    {acting && <InviteActionDialog invite={acting.invite} mode={acting.mode} close={() => setActing(null)} onChanged={resource.reload} />}
  </>;
}

function DevicesList({ data, revokeSession, revokeDevice }: { data: DevicesInfo; revokeSession: (id: number) => Promise<void>; revokeDevice: (id: number) => Promise<void> }) {
  const text = useAccountText();
  const { lang } = useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  async function run(key: string, action: () => Promise<void>) {
    if (busy) return;
    setBusy(key); setError(null);
    try { await action(); } catch (reason) { setError(reason); } finally { setBusy(null); }
  }
  return <div className="ac-devices">
    <section className="ac-device-group" aria-labelledby="ac-site-sessions">
      <div className="ac-device-head"><div><h3 id="ac-site-sessions">{text.siteSessions}</h3><p>{text.siteSessionsLead}</p></div><span className="ac-device-count">{data.sessions.length} {text.of} {data.session_limit} {text.inUse}</span></div>
      {data.sessions.length === 0 ? <p className="ac-device-empty">{text.noSessions}</p> : <ul className="ac-device-list">{data.sessions.map((item) => <li key={`s${item.id}`} className="ac-device-item">
        <span className="ac-device-icon"><Icon name="globe" /></span>
        <div className="ac-device-info"><strong>{item.label}{item.current && <span className="ac-device-current">{text.thisBrowser}</span>}</strong><span>{text.lastSeen}: {dateLabel(item.last_seen_at, lang)}{item.ip_masked && <> · {text.network} {item.ip_masked}</>}</span></div>
        {!item.current && <button className="btn ghost ac-small-btn" disabled={busy !== null} onClick={() => void run(`s${item.id}`, () => revokeSession(item.id))} aria-label={`${text.endSession}: ${item.label}`}>{busy === `s${item.id}` ? text.working : text.endSession}</button>}
      </li>)}</ul>}
    </section>
    <section className="ac-device-group" aria-labelledby="ac-app-devices">
      <div className="ac-device-head"><div><h3 id="ac-app-devices">{text.appDevices}</h3><p>{text.appDevicesLead}</p></div><span className="ac-device-count">{data.devices.length} {text.of} {data.device_limit} {text.inUse}</span></div>
      {data.device_changes && <p className="ac-device-changes"><strong>{text.deviceChanges.replace('{days}', daysText(data.device_changes.days, lang)).replace('{used}', String(data.device_changes.used)).replace('{limit}', String(data.device_changes.limit))}</strong> {text.deviceChangesHint}</p>}
      {data.devices.length === 0 ? <p className="ac-device-empty">{text.noAppDevices}</p> : <ul className="ac-device-list">{data.devices.map((item) => <li key={`d${item.id}`} className="ac-device-item">
        <span className="ac-device-icon"><Icon name={platformIcons[item.platform]} /></span>
        <div className="ac-device-info"><strong>{item.name}</strong><span>{platformNames[item.platform]} · {text.appVersion} {item.app_version} · {text.lastSeen}: {dateLabel(item.last_seen_at, lang)}{item.ip_masked && <> · {text.network} {item.ip_masked}</>}</span></div>
        <button className="btn ghost ac-small-btn" disabled={busy !== null} onClick={() => void run(`d${item.id}`, () => revokeDevice(item.id))} aria-label={`${text.removeDevice}: ${item.name}`}>{busy === `d${item.id}` ? text.working : text.removeDevice}</button>
      </li>)}</ul>}
    </section>
    <ErrorNotice error={error} />
  </div>;
}

function MemberDevices({ memberId }: { memberId: number }) {
  const text = useAccountText();
  const resource = useResource<DevicesInfo>(`/api/admin/members/${memberId}/devices`);
  async function revoke(kind: 'sessions' | 'devices', id: number) {
    // Список обновляется и после отказа: строка могла устареть (вход уже завершен в другом месте)
    try { await request(`/api/admin/members/${memberId}/${kind}/${id}/revoke`, { method: 'POST', body: {} }); }
    finally { resource.reload(); }
  }
  return <div className="ac-member-devices"><h3>{text.memberDevices}</h3>
    {resource.loading && !resource.data ? <Loading /> : resource.error ? <ErrorNotice error={resource.error} retry={resource.reload} /> : resource.data && <DevicesList data={resource.data} revokeSession={(id) => revoke('sessions', id)} revokeDevice={(id) => revoke('devices', id)} />}
  </div>;
}

function PasswordField({ label, value, onChange, autoComplete, hint }: { label: string; value: string; onChange: (value: string) => void; autoComplete: string; hint?: string }) {
  const id = useId();
  return <><label className="ac-field" htmlFor={id}>{label}<input id={id} type="password" value={value} onChange={(event) => onChange(event.target.value)} autoComplete={autoComplete} maxLength={128} required aria-describedby={hint ? `${id}-hint` : undefined} /></label>{hint && <p className="ac-otp-hint" id={`${id}-hint`}>{hint}</p>}</>;
}

type OwnAction = 'password' | 'everywhere';
// Свое действие: смена пароля или выход на всех устройствах; администратор подтверждает кодом 2FA
function OwnAccessDialog({ action, close, onDone }: { action: OwnAction; close: () => void; onDone: (message: string) => void }) {
  const text = useAccountText();
  const { user } = useApp();
  const admin = user?.role === 'admin';
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState('');
  const formId = useId();
  const password = action === 'password';
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (password && !current) { setValidation(text.currentPasswordRequired); return; }
    if (password && ([...next].length < 12 || [...next].length > 128)) { setValidation(text.newPasswordInvalid); return; }
    if (admin && !/^\d{6}$/.test(code)) { setValidation(text.otpInvalid); return; }
    setBusy(true); setError(null); setValidation('');
    const factor = admin ? { code } : {};
    try {
      if (password) await request('/api/me/password', { method: 'POST', body: { current_password: current, new_password: next, ...factor } });
      else await request('/api/me/sign-out-everywhere', { method: 'POST', body: factor });
      onDone(password ? text.passwordChanged : text.signedOutEverywhere);
      close();
    } catch (reason) { setCurrent(''); setCode(''); setError(reason); }
    finally { setBusy(false); }
  }
  return <Dialog title={password ? text.changePassword : text.signOutEverywhere} busy={busy} close={close} footer={<><button className="btn" disabled={busy} onClick={close}>{text.cancel}</button><button className={`btn ${password ? 'primary' : 'ac-danger'}`} type="submit" form={formId} disabled={busy}>{busy ? text.working : password ? text.changePassword : text.signOutEverywhere}</button></>}>
    <p>{password ? text.changePasswordDescription : text.signOutDescription}</p>
    <form id={formId} noValidate onSubmit={(event) => void submit(event)}>
      {password && <><PasswordField label={text.currentPassword} value={current} onChange={(value) => { setCurrent(value); setValidation(''); }} autoComplete="current-password" /><PasswordField label={text.newPassword} value={next} onChange={(value) => { setNext(value); setValidation(''); }} autoComplete="new-password" hint={text.newPasswordHint} /></>}
      {admin && <OtpField value={code} onChange={(value) => { setCode(value); setValidation(''); }} />}
      {validation && <p className="ac-form-error" role="alert">{validation}</p>}<ErrorNotice error={error} />
    </form>
  </Dialog>;
}

export function DevicesPage() {
  const text = useAccountText();
  const resource = useResource<DevicesInfo>('/api/me/devices');
  const [own, setOwn] = useState<OwnAction | null>(null);
  const [done, setDone] = useState('');
  async function revoke(kind: 'sessions' | 'devices', id: number) {
    try { await request(`/api/me/${kind}/${id}/revoke`, { method: 'POST', body: {} }); }
    finally { resource.reload(); }
  }
  return <>
    <Heading kicker={text.security} title={text.devicesTitle} description={text.devicesLead} />
    <section className="card ac-security-card" aria-labelledby="ac-account-security">
      <div><h3 id="ac-account-security">{text.accountSection}</h3><p>{text.accountSectionLead}</p></div>
      <div className="ac-security-actions"><button className="btn" onClick={() => { setDone(''); setOwn('password'); }}><Icon name="key" />{text.changePassword}</button><button className="btn" onClick={() => { setDone(''); setOwn('everywhere'); }}><Icon name="logout" />{text.signOutEverywhere}</button></div>
      {done && <p className="ac-security-done" role="status"><Icon name="check" />{done}</p>}
    </section>
    {own && <OwnAccessDialog action={own} close={() => setOwn(null)} onDone={(message) => { setDone(message); resource.reload(); }} />}
    <section className="card ac-devices-card">
      {resource.loading && !resource.data ? <Loading /> : resource.error ? <ErrorNotice error={resource.error} retry={resource.reload} /> : resource.data && <DevicesList data={resource.data} revokeSession={(id) => revoke('sessions', id)} revokeDevice={(id) => revoke('devices', id)} />}
    </section>
  </>;
}

export function DownloadLogPage() {
  const text = useAccountText();
  const { lang } = useApp();
  const [params, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const userId = /^\d+$/.test(params.get('user') ?? '') ? params.get('user') : null;
  const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (userId) query.set('user_id', userId);
  const resource = useResource<ListResult<DownloadEvent>>(`/api/admin/downloads?${query}`);
  const items = resource.fresh ? resource.data?.items ?? [] : [];
  const filtered = userId ? items.find((item) => String(item.user?.id) === userId)?.user : null;
  return <>
    <Heading kicker={text.admin} title={text.downloadLog} description={text.downloadLogLead} />
    {userId && <p className="ac-log-filter">{text.memberFilter}: <strong>{filtered ? personName(filtered) : `#${userId}`}</strong> <button className="btn ghost ac-small-btn" onClick={() => { setParams({}); setOffset(0); }}>{text.showAll}</button></p>}
    <section className="card ac-members-card">
      {resource.loading && !resource.fresh ? <Loading /> : resource.error ? <ErrorNotice error={resource.error} retry={resource.reload} /> : items.length === 0 ? <div className="ac-empty"><Icon name="history" /><h3>{text.logEmpty}</h3><p>{text.logEmptyLead}</p></div>
        : <table className="ac-table ac-log-table"><caption className="ac-sr-only">{text.downloadLogLead}</caption><thead><tr><th>{text.when}</th><th>{text.member}</th><th>{text.platformCol}</th><th>{text.deviceCol}</th><th>{text.network}</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}>
          <td data-label={text.when}>{dateLabel(item.at, lang)}</td>
          <td data-label={text.member}>{item.user ? <div className="ac-person"><span className="ac-avatar">{personName(item.user).split(/\s+/).map((part) => part[0]).slice(0, 2).join('')}</span><div><button className="ac-name-link" onClick={() => { setParams({ user: String(item.user!.id) }); setOffset(0); }}>{personName(item.user)}</button><span>{item.user.email}</span></div></div> : <span className="ac-muted">{text.deletedMember}</span>}</td>
          <td data-label={text.platformCol}><span className="ac-log-platform"><Icon name={platformIcons[item.platform]} />{platformNames[item.platform]} {item.version}</span></td>
          <td data-label={text.deviceCol}>{item.device}</td>
          <td data-label={text.network}>{item.ip_masked ?? '—'}</td>
        </tr>)}</tbody></table>}
    </section>
    {resource.data && <Pagination total={resource.data.total} offset={offset} busy={resource.loading} onChange={setOffset} />}
  </>;
}
