import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router';
import { request } from '../api/client';
import { errorText } from '../api/errors';
import { useApp } from '../app/context';
import { Icon } from '../ui';
import { accountText } from './locales';
import { inviteStatus, looksLikeEmail, personName, safeDownloadUrl, type Download, type Invite, type InviteStatus, type ListResult, type Platform, type User } from './types';
import './account.css';

const PAGE_SIZE = 20;

function useAccountText() {
  const { lang } = useApp();
  return accountText[lang];
}

function useResource<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    request<T>(path).then((result) => {
      if (active) { setData(result); setLoading(false); }
    }).catch((reason: unknown) => {
      if (active) { setError(reason); setLoading(false); }
    });
    return () => { active = false; };
  }, [path, revision]);
  return { data, error, loading, reload };
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
        {user?.role === 'admin' && <><div className="ac-nav-caption">{text.admin}</div>
          <NavLink to="/admin/members" className={navClass}><Icon name="users" /><span>{text.members}</span></NavLink>
          <NavLink to="/admin/invites" className={navClass}><Icon name="mail" /><span>{text.invites}</span></NavLink>
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
  const find = (platform: Platform): Download => resource.data?.items.find((item) => item.platform === platform) ?? {
    platform, available: false, version: null, filename: null, size_bytes: null, sha256: null, url: null,
  };
  const ios = find('ios');
  const iosUrl = safeDownloadUrl(ios);
  return <>
    <Heading kicker={text.application} title={text.downloadsTitle} description={text.downloadsLead} />
    <div className="ac-download-banner"><div className="ac-banner-icon"><Icon name="shield" /></div><div><strong>{text.bannerTitle}</strong><p>{text.bannerLead}</p></div></div>
    {resource.loading ? <Loading /> : resource.error ? <ErrorNotice error={resource.error} retry={resource.reload} /> : <>
      <div className="ac-download-grid">{(['windows', 'macos', 'linux', 'android'] as const).map((platform) => {
        const item = find(platform), url = safeDownloadUrl(item);
        const descriptions = { windows: text.windowsLead, macos: text.macosLead, linux: text.linuxLead, android: text.androidLead };
        return <article key={platform} className={`ac-download-card ${platform === 'windows' ? 'is-featured' : ''}`} data-platform={platform}>
          <div className="ac-os-icon"><Icon name={platformIcons[platform]} /></div>
          <div className="ac-download-title"><h2>{platformNames[platform]}</h2>{platform === 'windows' && <span className="ac-tag">{text.desktop}</span>}</div>
          <p>{descriptions[platform]}</p><div className="ac-platform-space" />
          {url ? <a className={`btn ${platform === 'windows' ? 'primary' : ''} ac-download-btn`} href={url} download><Icon name="download" />{text.download} {platformNames[platform]}</a>
            : <button className="btn ac-download-btn" disabled><Icon name="download" />{text.unavailable}</button>}
          <div className="ac-file-label">{url ? <>{item.version && <span>{text.version} {item.version}</span>}{item.filename && <span>{item.filename}</span>}{item.size_bytes !== null && <span>{new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(item.size_bytes / 1024 / 1024)} MB</span>}</> : text.unavailable}</div>
          {url && item.sha256 && <details className="ac-checksum"><summary>{text.checksum}</summary><code>{item.sha256}</code></details>}
        </article>;
      })}</div>
      <div className="ac-ios card" data-platform="ios"><div className="ac-os-icon"><Icon name="apple" /></div><div><h3>{text.iosTitle}</h3><p>{text.iosLead}</p></div>
        {iosUrl ? <a className="btn" href={iosUrl} target="_blank" rel="noopener noreferrer">{text.appStore}</a> : <span className="ac-status is-muted">{text.appStorePending}</span>}
      </div>
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
function Person({ user, onClick }: { user: User; onClick?: () => void }) {
  const name = personName(user);
  return <div className="ac-person"><span className="ac-avatar">{name.split(/\s+/).map((part) => part[0]).slice(0, 2).join('')}</span><div>{onClick ? <button className="ac-name-link" onClick={onClick}>{name}</button> : <strong>{name}</strong>}<span>{user.email}</span></div></div>;
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

type MemberAction = 'block' | 'restore' | 'promote' | 'demote' | 'reset';
function MemberDialog({ member, close, onChanged }: { member: User; close: () => void; onChanged: () => void }) {
  const text = useAccountText();
  const { user, lang } = useApp();
  const [action, setAction] = useState<MemberAction | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState('');
  const [result, setResult] = useState<SecretResult | null>(null);
  const formId = useId();
  const labels = { block: text.revokeAccess, restore: text.restoreAccess, promote: text.promote, demote: text.demote, reset: text.resetCode };
  const descriptions = { block: text.revokeDescription, restore: text.restoreDescription, promote: text.promoteDescription, demote: text.demoteDescription, reset: text.resetDescription };
  function choose(next: MemberAction) { setAction(next); setCode(''); setError(null); setValidation(''); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!action || busy) return;
    if (!/^\d{6}$/.test(code)) { setValidation(text.otpInvalid); return; }
    setBusy(true); setError(null); setValidation('');
    try {
      if (action === 'reset') {
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
    footer={action ? <><button className="btn" disabled={busy} onClick={() => { setAction(null); setCode(''); setError(null); }}>{text.cancel}</button><button className={`btn ${action === 'block' ? 'ac-danger' : 'primary'}`} form={formId} type="submit" disabled={busy}>{busy ? text.working : text.confirm}</button></> : <button className="btn" onClick={close}>{text.done}</button>}>
    <Person user={member} /><dl className="ac-details"><div><dt>{text.role}</dt><dd>{member.role === 'admin' ? text.roleAdmin : text.roleMember}</dd></div><div><dt>{text.access}</dt><dd><AccessBadge active={member.status === 'active'} /></dd></div><div><dt>{text.created}</dt><dd>{dateLabel(member.created_at, lang)}</dd></div></dl>
    {action ? <form id={formId} noValidate onSubmit={(event) => void submit(event)}><p>{descriptions[action]}</p><OtpField value={code} onChange={(value) => { setCode(value); setValidation(''); }} />{validation && <p className="ac-form-error" role="alert">{validation}</p>}<ErrorNotice error={error} /></form>
      : member.id !== user?.id && <div className="ac-member-actions"><button className="btn" onClick={() => choose(member.status === 'active' ? 'block' : 'restore')}>{member.status === 'active' ? text.revokeAccess : text.restoreAccess}</button><button className="btn" onClick={() => choose(member.role === 'admin' ? 'demote' : 'promote')}>{member.role === 'admin' ? text.demote : text.promote}</button><button className="btn" onClick={() => choose('reset')}>{text.resetCode}</button></div>}
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
          <td data-label={text.protection}><span className={`ac-2fa ${item.totp_enabled ? '' : 'is-off'}`}><Icon name={item.totp_enabled ? 'shield' : 'key'} />{item.totp_enabled ? text.twoFactorOn : text.twoFactorOff}</span></td><td data-label={text.access}><AccessBadge active={item.status === 'active'} /></td><td className="ac-table-action"><button className="btn ghost ac-small-btn" onClick={() => setMember(item)} aria-label={`${text.details}: ${personName(item)}`}>{text.details}<Icon name="chevron" /></button></td>
        </tr>)}</tbody></table>}
    </section>
    {resource.data && <Pagination total={resource.data.total} offset={offset} busy={resource.loading} onChange={setOffset} />}
    <p className="ac-boundary"><Icon name="lock" />{text.accessBoundary}</p>
    {member && <MemberDialog member={member} close={() => setMember(null)} onChanged={resource.reload} />}
    {creating && <InviteDialog close={() => setCreating(false)} onCreated={resource.reload} />}
  </>;
}

function RevokeInviteDialog({ invite, close, onChanged }: { invite: Invite; close: () => void; onChanged: () => void }) {
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
    try { await request(`/api/admin/invites/${invite.id}/revoke`, { method: 'POST', body: { code } }); onChanged(); close(); }
    catch (reason) { setCode(''); setError(reason); }
    finally { setBusy(false); }
  }
  return <Dialog title={text.revokeInviteTitle} busy={busy} close={close} footer={<><button className="btn" disabled={busy} onClick={close}>{text.cancel}</button><button className="btn ac-danger" type="submit" form={formId} disabled={busy}>{busy ? text.working : text.revokeInvite}</button></>}>
    <p><strong>{invite.email}</strong></p><p>{text.revokeInviteDescription}</p><form id={formId} noValidate onSubmit={(event) => void submit(event)}><OtpField value={code} onChange={(value) => { setCode(value); setValidation(''); }} />{validation && <p className="ac-form-error" role="alert">{validation}</p>}<ErrorNotice error={error} /></form>
  </Dialog>;
}

export function InvitesPage() {
  const text = useAccountText();
  const { lang } = useApp();
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState<'all' | InviteStatus>('all');
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<Invite | null>(null);
  const resource = useResource<ListResult<Invite>>(`/api/admin/invites?limit=${PAGE_SIZE}&offset=${offset}`);
  const items = resource.data?.items.filter((item) => filter === 'all' || inviteStatus(item) === filter) ?? [];
  return <>
    <Heading kicker={text.admin} title={text.invites} description={text.invitesLead} action={<button className="btn primary" onClick={() => setCreating(true)}><Icon name="plus" />{text.createInvite}</button>} />
    <section className="card ac-invites-card"><div className="ac-invites-head"><div><h2>{text.invitesHeading}</h2><p>{text.invitesSub}</p></div><label className="ac-select-label"><span className="ac-sr-only">{text.inviteFilter}</span><select value={filter} onChange={(event) => setFilter(event.target.value as 'all' | InviteStatus)}><option value="all">{text.allStatuses}</option><option value="active">{text.inviteActive}</option><option value="used">{text.inviteUsed}</option><option value="revoked">{text.inviteRevoked}</option><option value="expired">{text.inviteExpired}</option></select></label></div>
      {resource.loading ? <Loading /> : resource.error ? <ErrorNotice error={resource.error} retry={resource.reload} /> : items.length === 0 ? <div className="ac-empty"><h3>{text.inviteEmpty}</h3><p>{text.inviteEmptyLead}</p></div> : items.map((invite) => {
        const status = inviteStatus(invite);
        return <article className="ac-invite-item" key={invite.id}><span className="ac-invite-icon"><Icon name={status === 'used' ? 'check' : 'mail'} /></span><div className="ac-invite-info"><div><strong>{invite.email}</strong><InviteBadge status={status} /></div><p>{invite.role === 'admin' ? text.roleAdmin : text.roleMember}<span>·</span>{text.expires}: {dateLabel(invite.expires_at, lang)}</p></div>{status === 'active' && <div className="ac-invite-actions"><button className="btn ghost ac-small-btn" onClick={() => setRevoking(invite)} aria-label={`${text.revokeInvite}: ${invite.email}`}>{text.revokeInvite}</button></div>}</article>;
      })}
    </section>
    {resource.data && <Pagination total={resource.data.total} offset={offset} busy={resource.loading} onChange={setOffset} />}
    <div className="ac-invite-help"><div className="ac-invite-help-icon"><Icon name="link" /></div><div><h3>{text.howTitle}</h3><p>{text.howLead}</p></div></div>
    {creating && <InviteDialog close={() => setCreating(false)} onCreated={resource.reload} />}
    {revoking && <RevokeInviteDialog invite={revoking} close={() => setRevoking(null)} onChanged={resource.reload} />}
  </>;
}
