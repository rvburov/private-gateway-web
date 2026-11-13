import { useEffect, useRef, useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';

import { request, ApiError } from '../api/client';
import { useApp } from '../app/context';
import { Icon, LanguageSwitch, ThemeButton } from '../ui';
import { authText } from './locales';
import { groupSecret, isEmailShape, isOtpComplete, svgDataUri } from './codes';
import { EMPTY_OTP, OtpInput, otpValue, type OtpDigits, type OtpHandle } from './OtpInput';
import './auth-ui.css';

type User = NonNullable<ReturnType<typeof useApp>['user']>;
type Step = 'login' | 'register' | 'two-factor' | 'recovery' | 'setup' | 'backup' | 'reset' | 'reset-done';
type LoginResponse = { status: 'ok' | 'totp_required' | 'totp_setup_required'; user: User | null };
type SetupResponse = { secret: string; otpauth_uri: string; qr_svg: string };
type EnrollmentResponse = { status: 'ok'; user: User; recovery_codes: string[] };
type LocalError = 'invalidEmail' | 'passwordRequired' | 'invalidPassword' | 'required' | 'invalidOtp' | 'invalidRecovery' | 'savedRequired' | 'expired';
type Failure = { local: LocalError } | { code: string };

function Heading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <div className="auth-heading login-head"><div className="eyebrow">{eyebrow}</div><h1 className="login-title" id="auth-title" tabIndex={-1}>{title}</h1><p className="login-sub">{description}</p></div>;
}

function Steps({ first, second, active }: { first: string; second: string; active: 0 | 1 }) {
  const { lang } = useApp();
  return <ol className="auth-steps stepper line" aria-label={authText[lang].steps}>
    <li className={`stepper-item ${active === 0 ? 'current' : 'done'}`} aria-current={active === 0 ? 'step' : undefined}><span className="stepper-n">{active === 1 ? <Icon name="check" /> : '1'}</span><span className="stepper-label">{first}</span></li>
    <li className={`stepper-item ${active === 1 ? 'current' : ''}`} aria-current={active === 1 ? 'step' : undefined}><span className="stepper-n">2</span><span className="stepper-label">{second}</span></li>
  </ol>;
}

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  id: string; label: string; aside?: ReactNode; hint?: string;
}
function Field({ id, label, aside, hint, type, ...props }: FieldProps) {
  const { lang } = useApp();
  const [visible, setVisible] = useState(false);
  const password = type === 'password';
  return <div className="auth-field field">
    <div className="login-label-row"><label className="field-label" htmlFor={id}>{label}</label>{aside}</div>
    <div className={`auth-input-wrap input-wrap ${password ? 'login-pw' : ''}`}>
      <input {...props} id={id} className="input" type={password && visible ? 'text' : type} aria-describedby={hint ? `${id}-hint` : undefined} />
      {password && <button className="auth-eye login-eye" type="button" aria-label={visible ? authText[lang].hide : authText[lang].show} aria-pressed={visible} onClick={() => setVisible(!visible)}><Icon name="eye" /></button>}
    </div>
    {hint && <small id={`${id}-hint`} className="field-hint">{hint}</small>}
  </div>;
}

function NetworkBackground() {
  return <svg className="auth-network-background" viewBox="0 0 700 800" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false"><g className="auth-network-lines"><path d="M430 80h98q20 0 20 20v66q0 20 20 20h132M610 0v86q0 20-20 20H430q-20 0-20 20v106q0 20-20 20h-94M700 336H582q-20 0-20-20v-44q0-20-20-20H410M700 508h-78q-20 0-20-20v-56q0-20-20-20H470q-20 0-20 20v76q0 20-20 20H302M700 668H520q-20 0-20-20v-60q0-20-20-20h-78M264 800v-86q0-20 20-20h146q20 0 20-20V528" /></g><g className="auth-network-junctions">{[[430,80,5],[548,166,4],[410,232,4],[296,252,5],[562,292,4],[582,412,4],[470,412,4],[302,528,5],[450,612,4],[520,668,4],[284,694,5]].map(([cx,cy,r]) => <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} />)}</g></svg>;
}

function AuthBrand() {
  const { lang } = useApp();
  return <Link className="login-brandrow" to="/" aria-label="Private Gateway"><img className="brand-mark" src="/assets/logo.svg" alt="" /><div className="login-brandrow-text"><div className="brand-name">Private Gateway</div><div className="brand-sub">{authText[lang].brandSub}</div></div></Link>;
}

export function AuthPage() {
  const location = useLocation();
  return <AuthFlow key={location.pathname} entry={location.pathname === '/register' ? 'register' : location.pathname === '/reset' ? 'reset' : 'login'} />;
}

function AuthFlow({ entry }: { entry: 'login' | 'register' | 'reset' }) {
  const { lang, setUser } = useApp();
  const text = authText[lang];
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(entry);
  const stepRef = useRef<Step>(entry);
  stepRef.current = step;
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [invite, setInvite] = useState('');
  const [resetCode, setResetCode] = useState('');
  const [recovery, setRecovery] = useState('');
  const [remember, setRemember] = useState(false);
  const [digits, setDigits] = useState<OtpDigits>(EMPTY_OTP);
  const [setup, setSetup] = useState<SetupResponse | null>(null);
  const [enrollment, setEnrollment] = useState<EnrollmentResponse | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [copyState, setCopyState] = useState<'copied' | 'copyFailed' | null>(null);
  const [retryAt, setRetryAt] = useState(0);
  const [clock, setClock] = useState(Date.now());
  const requestSequence = useRef(0);
  const mounted = useRef(true);
  const otpRef = useRef<OtpHandle>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const seconds = Math.max(0, Math.ceil((retryAt - clock) / 1000));

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; requestSequence.current += 1; };
  }, []);
  useEffect(() => {
    if (!retryAt) return;
    const interval = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [retryAt]);
  useEffect(() => {
    panelRef.current?.querySelector<HTMLHeadingElement>('#auth-title')?.focus();
  }, [step]);
  useEffect(() => {
    if (!failure) return;
    if ('local' in failure && failure.local === 'invalidEmail') panelRef.current?.querySelector<HTMLInputElement>('#auth-email')?.focus();
    else if (stepRef.current === 'login') panelRef.current?.querySelector<HTMLInputElement>('#auth-password')?.focus();
  }, [failure]);
  useEffect(() => {
    if (step !== 'backup' || saved) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [step, saved]);

  const isCurrent = (id: number) => mounted.current && id === requestSequence.current;
  const errorMessage = !failure ? '' : 'local' in failure ? text[failure.local] : text.errors[failure.code as keyof typeof text.errors] ?? text.unknown;
  const error = <>{errorMessage && <div className="auth-error" role="alert">{errorMessage}</div>}{seconds > 0 && <p className="auth-error" role="status">{text.rateLimited.replace('{seconds}', String(seconds))}</p>}</>;
  const submitButton = (label: string, icon = 'arrow', disabled = false) => <button className="btn primary lg block auth-submit" type="submit" disabled={busy || seconds > 0 || disabled} aria-busy={busy}>{busy ? text.busy : label}{!busy && <Icon name={icon} />}</button>;

  function onError(error: unknown) {
    if (error instanceof ApiError) {
      if (error.status === 429) {
        setRetryAt(Date.now() + Math.max(1, error.retryAfter ?? 900) * 1000);
        setClock(Date.now());
        setFailure(null);
      } else if (['login_expired', 'unauthorized', 'already_configured'].includes(error.code)) {
        setSetup(null); setStep('login'); setFailure({ local: 'expired' });
      } else setFailure({ code: error.code });
    } else setFailure({ code: 'unknown' });
    setPassword('');
    setDigits(EMPTY_OTP);
    setRecovery('');
  }

  async function run(action: (id: number) => Promise<void>) {
    if (busy || seconds > 0) return;
    const id = ++requestSequence.current;
    setBusy(true); setFailure(null); setCopyState(null);
    try { await action(id); }
    catch (error) { if (isCurrent(id)) onError(error); }
    finally { if (isCurrent(id)) setBusy(false); }
  }

  function finish(user: User) {
    setUser(user); setPassword(''); setSetup(null); setEnrollment(null);
    navigate('/downloads', { replace: true });
  }

  async function showOutcome(outcome: LoginResponse, id: number) {
    if (!isCurrent(id)) return;
    setPassword('');
    if (outcome.status === 'ok' && outcome.user) { finish(outcome.user); return; }
    if (outcome.status === 'totp_required') { setStep('two-factor'); return; }
    if (outcome.status === 'totp_setup_required') {
      setStep('setup');
      const result = await request<SetupResponse>('/api/auth/2fa/setup', { method: 'POST', body: {} });
      if (isCurrent(id)) setSetup(result);
      return;
    }
    throw new Error('Unexpected sign-in response');
  }

  function validateIdentity(newPassword = false) {
    if (!isEmailShape(email)) { setFailure({ local: 'invalidEmail' }); return false; }
    if (!password) { setFailure({ local: 'passwordRequired' }); return false; }
    if (newPassword && ([...password].length < 12 || [...password].length > 128)) { setFailure({ local: 'invalidPassword' }); return false; }
    return true;
  }

  function passwordSubmit(event: FormEvent) {
    event.preventDefault();
    if (!validateIdentity()) return;
    void run(async id => {
      const result = await request<LoginResponse>('/api/auth/login', { method: 'POST', body: { email: email.trim(), password } });
      await showOutcome(result, id);
    });
  }
  function registerSubmit(event: FormEvent) {
    event.preventDefault();
    if (!invite.trim() || !name.trim()) { setFailure({ local: 'required' }); return; }
    if (!validateIdentity(true)) return;
    void run(async id => {
      const result = await request<LoginResponse>('/api/auth/register', { method: 'POST', body: { invite_code: invite.trim(), email: email.trim(), display_name: name.trim(), password } });
      await showOutcome(result, id);
    });
  }
  function codeSubmit(event: FormEvent) {
    event.preventDefault();
    const code = otpValue(digits);
    if (step === 'recovery' ? !recovery.trim() : !isOtpComplete(code)) {
      setFailure({ local: step === 'recovery' ? 'invalidRecovery' : 'invalidOtp' }); otpRef.current?.focus(); return;
    }
    void run(async id => {
      if (step === 'setup') {
        const result = await request<EnrollmentResponse>('/api/auth/2fa/setup/confirm', { method: 'POST', body: { code } });
        if (isCurrent(id)) { setEnrollment(result); setSetup(null); setDigits(EMPTY_OTP); setStep('backup'); }
      } else {
        const result = await request<LoginResponse>('/api/auth/2fa', { method: 'POST', body: { ...(step === 'recovery' ? { recovery_code: recovery.trim() } : { code }), remember_device: remember } });
        await showOutcome(result, id);
      }
    });
  }
  function resetSubmit(event: FormEvent) {
    event.preventDefault();
    if (!resetCode.trim()) { setFailure({ local: 'required' }); return; }
    if (!validateIdentity(true)) return;
    void run(async id => {
      await request('/api/auth/reset', { method: 'POST', body: { email: email.trim(), code: resetCode.trim(), new_password: password } });
      if (isCurrent(id)) { setPassword(''); setResetCode(''); setStep('reset-done'); }
    });
  }
  function restart() {
    void run(async id => {
      await request('/api/auth/logout', { method: 'POST', body: {} });
      if (isCurrent(id)) { setStep('login'); setSetup(null); setDigits(EMPTY_OTP); setRecovery(''); setPassword(''); }
    });
  }
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); if (mounted.current) setCopyState('copied'); }
    catch { if (mounted.current) setCopyState('copyFailed'); }
  }
  function downloadCodes() {
    if (!enrollment) return;
    const content = `${text.codesFileTitle}\n${text.codesFileAccount}: ${enrollment.user.email}\n\n${enrollment.recovery_codes.join('\n')}\n\n${text.backupNote}\n`;
    const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = 'private-gateway-recovery-codes.txt'; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const accountRow = <div className="auth-account login-acct"><Icon name="user" /><div><strong>{text.confirmation}</strong><span>{email}</span></div><button className="auth-link login-link" type="button" onClick={restart} disabled={busy}>{text.notYou}</button></div>;
  const otp = <div className="auth-field field"><span className="field-label" id="auth-otp-label">{text.otp}</span><OtpInput ref={otpRef} id="auth-otp" labelledBy="auth-otp-label" value={digits} onChange={next => { setDigits(next); setFailure(null); }} readOnly={busy} invalid={Boolean(failure)} /></div>;
  const emailField = (label: string = text.email) => <Field id="auth-email" label={label} type="email" value={email} autoComplete="username" inputMode="email" spellCheck={false} autoCapitalize="none" required maxLength={254} onChange={event => setEmail(event.target.value)} />;

  let content: ReactNode;
  // Участник входит одним шагом; код 2FA и «запомнить устройство» — только на шаге администратора
  if (step === 'login') content = <form className="auth-form" onSubmit={passwordSubmit} noValidate aria-labelledby="auth-title">
    <Heading eyebrow={text.account} title={text.loginTitle} description={text.loginDescription} />{error}
    {emailField()}
    <Field id="auth-password" label={text.password} type="password" value={password} autoComplete="current-password" required maxLength={128} onChange={event => setPassword(event.target.value)} aside={<Link className="auth-link login-link" to="/reset">{text.forgot}</Link>} />
    {submitButton(text.signIn)}<div className="login-alt"><span className="muted">{text.noAccount}</span><Link className="auth-link login-link" to="/register">{text.invitationLink}<Icon name="chevron" /></Link></div>
  </form>;
  else if (step === 'register') content = <form className="auth-form" onSubmit={registerSubmit} noValidate aria-labelledby="auth-title">
    <Heading eyebrow={text.invitation} title={text.welcome} description={text.registerDescription} />{error}
    <Field id="auth-invite" label={text.invitationCode} hint={text.invitationHint} value={invite} onChange={event => setInvite(event.target.value)} autoComplete="off" spellCheck={false} required maxLength={256} />
    <Field id="auth-name" label={text.name} value={name} onChange={event => setName(event.target.value)} autoComplete="name" required maxLength={100} />
    {emailField(text.invitedEmail)}
    <Field id="auth-password" label={text.password} type="password" hint={text.passwordHint} value={password} onChange={event => setPassword(event.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} />
    {submitButton(text.createAccount)}<p className="auth-alt">{text.alreadyAccount} <Link className="auth-link login-link" to="/login">{text.signIn}</Link></p>
  </form>;
  else if (step === 'two-factor' || step === 'recovery') content = <form className="auth-form" onSubmit={codeSubmit} noValidate aria-labelledby="auth-title">
    <Steps first={text.passwordStep} second={text.codeStep} active={1} /><Heading eyebrow={text.secondStep} title={step === 'recovery' ? text.recoveryTitle : text.confirmTitle} description={step === 'recovery' ? text.recoveryDescription : text.confirmDescription} />
    {accountRow}{error}
    {step === 'two-factor' ? otp : <Field id="auth-recovery" label={text.recoveryCode} hint={text.recoveryHint} value={recovery} onChange={event => setRecovery(event.target.value)} autoComplete="off" spellCheck={false} autoCapitalize="none" required maxLength={128} />}
    <label className="auth-check check login-check"><input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)} /><span className="check-text"><span>{text.remember}</span><small className="field-hint">{text.rememberHint}</small></span></label>
    {submitButton(text.enterAccount, 'shield')}
    <div className="auth-bottom-links"><button className="auth-link login-link auth-back" type="button" onClick={restart} disabled={busy}><Icon name="arrow" />{text.back}</button><button className="auth-link login-link" type="button" disabled={busy} onClick={() => { setStep(step === 'recovery' ? 'two-factor' : 'recovery'); setDigits(EMPTY_OTP); setRecovery(''); setFailure(null); }}>{step === 'recovery' ? text.useAuthenticator : text.useRecovery}</button></div>
    {step === 'recovery' && <p className="auth-footnote">{text.noCodes}</p>}
  </form>;
  else if (step === 'setup') content = <form className="auth-form" onSubmit={codeSubmit} noValidate aria-labelledby="auth-title">
    <Steps first={entry === 'register' ? text.accountStep : text.passwordStep} second={text.setupStep} active={1} /><Heading eyebrow={text.setupEyebrow} title={text.setupTitle} description={text.setupDescription} />{error}
    {!setup ? <div role="status" className="auth-setup-loading">{busy ? text.loading : <button type="button" className="btn" onClick={() => void run(async id => { const result = await request<SetupResponse>('/api/auth/2fa/setup', { method: 'POST', body: {} }); if (isCurrent(id)) setSetup(result); })}>{text.retry}</button>}</div> : <div className="auth-setup"><div className="auth-qr"><img src={svgDataUri(setup.qr_svg)} alt={text.qrAlt} width={148} height={148} /></div><div className="auth-setup-text"><strong>{text.addAccount}</strong><p>{text.scanDescription}</p><span className="auth-mini-label">{text.manualKey}</span><code>{groupSecret(setup.secret)}</code><button type="button" className="auth-link login-link" onClick={() => void copy(setup.secret)}><Icon name="copy" />{text.copy}</button></div></div>}
    {copyState && <p role="status" className="auth-footnote">{text[copyState]}</p>}<strong className="auth-section-title">{text.enterSetupCode}</strong>{otp}
    {submitButton(text.continue, 'shield', !setup)}
    <button className="auth-link login-link" type="button" disabled={busy} onClick={restart}>{text.backLogin}</button>
  </form>;
  else if (step === 'backup' && enrollment) content = <form className="auth-form" onSubmit={event => { event.preventDefault(); if (!saved) { setFailure({ local: 'savedRequired' }); return; } finish(enrollment.user); }} aria-labelledby="auth-title">
    <Heading eyebrow={text.backupEyebrow} title={text.backupTitle} description={text.backupDescription} /><div className="auth-backup-note"><Icon name="key" />{text.backupWarning}</div>{error}
    <ol className="auth-backup-codes">{enrollment.recovery_codes.map(code => <li key={code}>{code}</li>)}</ol>
    <div className="auth-code-actions"><button className="btn" type="button" onClick={() => void copy(enrollment.recovery_codes.join('\n'))}><Icon name="copy" />{text.copy}</button><button className="btn" type="button" onClick={downloadCodes}><Icon name="download" />{text.downloadCodes}</button></div>
    {copyState && <p role="status" className="auth-footnote">{text[copyState]}</p>}
    <label className="auth-check"><input type="checkbox" checked={saved} onChange={event => { setSaved(event.target.checked); setFailure(null); }} /><span>{text.saved}</span></label>{submitButton(text.finish, 'check')}<p className="auth-footnote">{text.backupNote}</p>
  </form>;
  else if (step === 'reset-done') content = <div className="auth-form"><Heading eyebrow={text.resetEyebrow} title={text.resetDone} description={text.resetDoneDescription} /><Link className="btn primary lg block" to="/login">{text.backLogin}</Link></div>;
  else content = <form className="auth-form" onSubmit={resetSubmit} noValidate aria-labelledby="auth-title">
    <Heading eyebrow={text.resetEyebrow} title={text.resetTitle} description={text.resetDescription} />{error}{emailField()}
    <Field id="auth-reset-code" label={text.adminCode} value={resetCode} onChange={event => setResetCode(event.target.value)} autoComplete="off" required maxLength={256} />
    <Field id="auth-password" label={text.newPassword} type="password" hint={text.passwordHint} value={password} onChange={event => setPassword(event.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} />
    {submitButton(text.resetPassword, 'key')}<p className="auth-alt"><Link className="auth-link login-link" to="/login">{text.backLogin}</Link></p>
  </form>;

  return <div className="auth-page">
    <div className="auth-topbar"><LanguageSwitch /><Link className="auth-home-link" to="/">{text.home}<Icon name="arrow" /></Link></div>
    <div className="auth-shell login-page"><aside className="login-brand" aria-label={text.account}><NetworkBackground /><AuthBrand /><div className="login-hero"><div className="eyebrow">{text.account}</div><p className="login-hero-h">{text.hero}</p><p className="login-hero-p">{text.heroDescription}</p><p className="login-hero-note">{text.inviteOnly}</p></div><div className="login-brandfoot"><span>© {new Date().getFullYear()} Private Gateway</span><span>{text.devices}</span></div></aside>
    <div className="login-m-hero"><NetworkBackground /><div className="login-m-top"><AuthBrand /><ThemeButton /></div><p className="login-m-lead">{text.heroDescription}</p><p className="login-m-invite">{text.inviteOnly}</p></div>
    <section className="auth-content login-main"><div className="login-topline"><ThemeButton /></div><div className="login-center"><div ref={panelRef} className={`auth-panel login-form ${step === 'setup' ? 'wide' : ''}`}>{content}</div></div></section>
    <footer className="login-m-foot"><span>© {new Date().getFullYear()} Private Gateway</span></footer></div>
  </div>;
}
