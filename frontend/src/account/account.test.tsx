import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { request, ApiError } from '../api/client';
import { AccountLayout, DevicesPage, DownloadLogPage, DownloadsPage, InvitesPage, MembersPage } from './index';
import { inviteStatus, personName, safeDownloadUrl, type DevicesInfo, type Download, type DownloadEvent, type Invite, type User } from './types';
import { agents } from '../test/agents';

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>();
  return { ...original, request: vi.fn() };
});
const app = vi.hoisted(() => ({
  lang: 'en' as 'en' | 'ru',
  user: { id: 1, email: 'admin@example.com', display_name: 'Admin', role: 'admin', status: 'active', totp_enabled: true, created_at: '2026-01-01T00:00:00Z' },
  setUser: vi.fn(), reloadUser: vi.fn(),
}));
vi.mock('../app/context', () => ({ useApp: () => app }));

const member: User = { id: 2, email: 'member@example.com', display_name: 'Member One', role: 'member', status: 'active', totp_enabled: true, created_at: '2026-01-01T00:00:00Z' };
const invite: Invite = { id: 3, email: 'new@example.com', role: 'member', created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', used_at: null, revoked_at: null };
function file(overrides: Partial<Download> = {}): Download {
  return { platform: 'windows', available: false, version: null, filename: null, size_bytes: null, sha256: null, url: null, ...overrides };
}
function view(content: React.ReactNode, initial = '/downloads') {
  return render(<MemoryRouter initialEntries={[initial]}>{content}</MemoryRouter>);
}
function asVisitor(userAgent: string, maxTouchPoints = 0) {
  vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(userAgent);
  // jsdom не знает maxTouchPoints: свойство задается на каждый тест заново
  Object.defineProperty(window.navigator, 'maxTouchPoints', { configurable: true, get: () => maxTouchPoints });
}
beforeEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.mocked(request).mockReset();
  app.user.role = 'admin';
  app.lang = 'en';
  asVisitor(agents.windows);
});

describe('release links and invitation state', () => {
  it('allows only the private file endpoint and a genuine App Store HTTPS URL', () => {
    expect(safeDownloadUrl(file({ available: true, url: '/api/downloads/windows/file' }))).toBe('/api/downloads/windows/file');
    for (const url of ['javascript:alert(1)', 'https://other.example.com/client.exe', '/api/downloads/linux/file', '//example.com/file']) {
      expect(safeDownloadUrl(file({ available: true, url }))).toBeNull();
    }
    expect(safeDownloadUrl(file({ platform: 'ios', available: true, url: 'https://apps.apple.com/app/id123' }))).toBe('https://apps.apple.com/app/id123');
    expect(safeDownloadUrl(file({ platform: 'ios', available: true, url: 'https://apps.apple.com.evil.example/app/id123' }))).toBeNull();
    expect(safeDownloadUrl(file({ platform: 'ios', available: true, url: 'https://secret@apps.apple.com/app/id123' }))).toBeNull();
    expect(safeDownloadUrl(file({ platform: 'ios', available: false, url: 'https://apps.apple.com/app/id123' }))).toBeNull();
  });
  it('treats used and revoked invitations as unavailable even before expiry', () => {
    expect(inviteStatus(invite, Date.parse('2026-01-02'))).toBe('active');
    expect(inviteStatus(invite, Date.parse('2100-01-02'))).toBe('expired');
    expect(inviteStatus({ ...invite, used_at: '2026-01-02' })).toBe('used');
    expect(inviteStatus({ ...invite, revoked_at: '2026-01-02' })).toBe('revoked');
    expect(personName({ display_name: ' ', email: 'member@example.com' })).toBe('member@example.com');
  });
});

describe('account downloads', () => {
  it('shows all five platforms without invented release links', async () => {
    vi.mocked(request).mockResolvedValue({ items: [] });
    view(<DownloadsPage />);
    await screen.findByRole('heading', { name: 'Windows' });
    expect(screen.getAllByRole('button', { name: 'Not available yet' })).toHaveLength(4);
    for (const button of screen.getAllByRole('button', { name: 'Not available yet' })) expect(button).toBeDisabled();
    expect(screen.getByText('App Store · not available yet')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Download for/ })).not.toBeInTheDocument();
  });
  it('offers only the actual private release with its real metadata', async () => {
    vi.mocked(request).mockResolvedValue({ items: [file({ available: true, version: 'test-build', filename: 'client-test.exe', sha256: 'abc', size_bytes: 1024, url: '/api/downloads/windows/file' })] });
    view(<DownloadsPage />);
    expect(await screen.findByRole('link', { name: 'Download for Windows' })).toHaveAttribute('href', '/api/downloads/windows/file');
    expect(screen.getByText('client-test.exe')).toBeInTheDocument();
    expect(screen.getByText('Version test-build')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Not available yet' })).toHaveLength(3);
  });
  it('renders a retryable API error without presenting empty data as a valid catalog', async () => {
    vi.mocked(request).mockRejectedValueOnce(new ApiError(503, 'server_error')).mockResolvedValueOnce({ items: [] });
    view(<DownloadsPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('temporarily unavailable');
    expect(screen.queryByRole('heading', { name: 'Windows' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Windows' })).toBeInTheDocument();
  });
  it('hides administration links from a member', () => {
    app.user.role = 'member';
    view(<AccountLayout><p>Content</p></AccountLayout>);
    expect(screen.getByRole('link', { name: 'Download client' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Members' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Invitations' })).not.toBeInTheDocument();
  });
});

describe('admin invitations', () => {
  it('requires real TOTP and displays the newly created invitation code only until closing', async () => {
    vi.mocked(request).mockImplementation(async (path, options) => {
      if (options?.method === 'POST') return { invite, code: 'ONE-TIME-TEST-CODE' };
      return { items: [invite], total: 1 };
    });
    view(<InvitesPage />, '/admin/invites');
    await screen.findByText('new@example.com');
    fireEvent.click(screen.getByRole('button', { name: 'Create invitation' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Email address'), { target: { value: 'new@example.com' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create invitation' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('six-digit');
    expect(vi.mocked(request).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
    fireEvent.change(within(dialog).getByLabelText('Your current 2FA code'), { target: { value: '123456' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create invitation' }));
    expect(await screen.findByLabelText('One-time code')).toHaveValue('ONE-TIME-TEST-CODE');
    expect(request).toHaveBeenCalledWith('/api/admin/invites', { method: 'POST', body: { email: 'new@example.com', role: 'member', expires_in_days: 7, code: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByDisplayValue('ONE-TIME-TEST-CODE')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Create invitation' }));
    expect(screen.queryByDisplayValue('ONE-TIME-TEST-CODE')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Your current 2FA code')).toHaveValue('');
  });
  it('does not expose old invite secrets and retains a rejected revoke with a cleared code', async () => {
    vi.mocked(request).mockImplementation(async (_path, options) => {
      if (options?.method === 'POST') throw new ApiError(400, 'invalid_code');
      return { items: [invite], total: 1 };
    });
    view(<InvitesPage />, '/admin/invites');
    await screen.findByText('new@example.com');
    expect(screen.queryByRole('button', { name: 'Copy code' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Revoke: new@example.com' }));
    fireEvent.change(screen.getByLabelText('Your current 2FA code'), { target: { value: '123456' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Revoke' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid or has already been used');
    expect(screen.getByLabelText('Your current 2FA code')).toHaveValue('');
    expect(screen.getByText('Active', { selector: '.ac-status' })).toBeInTheDocument();
  });
});

describe('member administration', () => {
  it('changes access only after a successful server response and reloads the list', async () => {
    let blocked = false;
    vi.mocked(request).mockImplementation(async (_path, options) => {
      if (options?.method === 'PATCH') { blocked = true; return { ...member, status: 'blocked' }; }
      return { items: [{ ...member, status: blocked ? 'blocked' : 'active' }], total: 1 };
    });
    view(<MembersPage />, '/admin/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Details: Member One' }));
    fireEvent.click(screen.getByRole('button', { name: 'Revoke access' }));
    fireEvent.change(screen.getByLabelText('Your current 2FA code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByText('Access revoked')).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/api/admin/members/2', { method: 'PATCH', body: { status: 'blocked', code: '123456' } });
  });
  it('uses server-side pagination and resets the offset after changing the search', async () => {
    vi.mocked(request).mockResolvedValue({ items: [member], total: 22 });
    view(<MembersPage />, '/admin/members');
    await screen.findByText('Page 1 of 2');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(request).toHaveBeenLastCalledWith('/api/admin/members?q=&limit=20&offset=20'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Search members' }), { target: { value: 'Member' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(request).toHaveBeenLastCalledWith('/api/admin/members?q=Member&limit=20&offset=0'));
  });
});

const devicesInfo: DevicesInfo = {
  sessions: [
    { id: 11, label: 'Chrome · Windows', ip_masked: '203.0.113.0/24', created_at: '2026-11-01T00:00:00Z', last_seen_at: '2026-11-12T10:00:00Z', current: true },
    { id: 12, label: 'Safari · iOS', ip_masked: '198.51.100.0/24', created_at: '2026-11-02T00:00:00Z', last_seen_at: '2026-11-11T10:00:00Z', current: false },
  ],
  devices: [{ id: 21, name: 'Work laptop', platform: 'windows', app_version: '0.2.0', ip_masked: '203.0.113.0/24', created_at: '2026-11-03T00:00:00Z', last_seen_at: '2026-11-12T09:00:00Z' }],
  session_limit: 3,
  device_limit: 2,
  device_changes: { used: 1, limit: 3, days: 30 },
};

describe('member devices', () => {
  it('lists site sign-ins and app devices with limits and never offers to end the current browser', async () => {
    vi.mocked(request).mockResolvedValue(devicesInfo);
    view(<DevicesPage />, '/devices');
    await screen.findByText('Work laptop');
    expect(screen.getByText('2 of 3 in use')).toBeInTheDocument();
    expect(screen.getByText('1 of 2 in use')).toBeInTheDocument();
    expect(screen.getByText('This browser')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'End session: Chrome · Windows' })).toBeNull();
    expect(screen.getByRole('button', { name: 'End session: Safari · iOS' })).toBeEnabled();
  });
  it('ends another session and removes an app device through the member endpoints', async () => {
    vi.mocked(request).mockImplementation(async (path: string) => (path === '/api/me/devices' ? devicesInfo : undefined));
    view(<DevicesPage />, '/devices');
    fireEvent.click(await screen.findByRole('button', { name: 'End session: Safari · iOS' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/me/sessions/12/revoke', { method: 'POST', body: {} }));
    fireEvent.click(await screen.findByRole('button', { name: 'Remove device: Work laptop' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/me/devices/21/revoke', { method: 'POST', body: {} }));
  });
  it('explains an empty app device list in Russian', async () => {
    app.lang = 'ru';
    vi.mocked(request).mockResolvedValue({ ...devicesInfo, devices: [] });
    view(<DevicesPage />, '/devices');
    expect(await screen.findByText('Устройств пока нет. Войдите в приложение этим аккаунтом.')).toBeInTheDocument();
  });
});

describe('member devices in the admin card', () => {
  it('offers a personal device limit for a member but not on the admin own card', async () => {
    vi.mocked(request).mockImplementation(async (path: string) => (path.endsWith('/devices') ? devicesInfo : { items: [member, app.user], total: 2 }));
    view(<MembersPage />, '/admin/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Details: Member One' }));
    expect(await screen.findByRole('button', { name: 'Change device limit' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Details: Admin' }));
    await within(screen.getByRole('dialog')).findByText('Work laptop');
    expect(screen.queryByRole('button', { name: 'Change device limit' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Download history' })).toBeInTheDocument();
  });
  it('saves a personal limit with a 2FA code and an empty field returns to the default', async () => {
    vi.mocked(request).mockImplementation(async (path: string, options) => {
      if (options?.method === 'PATCH') return { ...member, device_limit: null };
      return path.endsWith('/devices') ? devicesInfo : { items: [{ ...member, device_limit: 4 }], total: 1 };
    });
    view(<MembersPage />, '/admin/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Details: Member One' }));
    fireEvent.click(screen.getByRole('button', { name: 'Change device limit' }));
    const field = screen.getByLabelText('Device limit');
    expect(field).toHaveValue('4');
    fireEvent.change(field, { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Your current 2FA code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/admin/members/2', { method: 'PATCH', body: { device_limit: null, code: '123456' } }));
  });
  it('reloads the device list even when removing a device fails', async () => {
    let calls = 0;
    vi.mocked(request).mockImplementation(async (path: string) => {
      if (path === '/api/me/devices') { calls += 1; return devicesInfo; }
      throw new ApiError(404, 'not_found');
    });
    view(<DevicesPage />, '/devices');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove device: Work laptop' }));
    await waitFor(() => expect(calls).toBe(2));
  });
});

describe('download log', () => {
  const event: DownloadEvent = { id: 5, at: '2026-11-12T10:00:00Z', platform: 'macos', version: '1.2.3', filename: 'PrivateGateway-1.2.3-osx-arm64.dmg', ip_masked: '203.0.113.0/24', device: 'Safari · macOS', user: { id: 2, email: 'member@example.com', display_name: 'Member One' } };
  it('shows who downloaded which release and filters by member', async () => {
    vi.mocked(request).mockResolvedValue({ items: [event], total: 1 });
    view(<DownloadLogPage />, '/admin/downloads');
    await screen.findByText('Safari · macOS');
    expect(request).toHaveBeenCalledWith('/api/admin/downloads?limit=20&offset=0');
    expect(screen.getByText('macOS 1.2.3')).toBeInTheDocument();
    expect(screen.getByText('203.0.113.0/24')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Member One' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/admin/downloads?limit=20&offset=0&user_id=2'));
    expect(await screen.findByRole('button', { name: 'Show all members' })).toBeInTheDocument();
  });
  it('keeps the record of a removed member', async () => {
    vi.mocked(request).mockResolvedValue({ items: [{ ...event, user: null }], total: 1 });
    view(<DownloadLogPage />, '/admin/downloads');
    expect(await screen.findByText('Deleted member')).toBeInTheDocument();
  });
});

describe('downloads for the visitor system', () => {
  const allAvailable = ['windows', 'macos', 'linux', 'android'].map((platform) => file({ platform: platform as Download['platform'], available: true, version: '0.2.0', url: `/api/downloads/${platform}/file` }));
  const titles = () => screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent);
  const cases: [string, string, number, string][] = [
    ['Windows', agents.windows, 0, 'Windows'],
    ['macOS', agents.macos, 0, 'macOS'],
    ['Linux', agents.linux, 0, 'Linux'],
    ['Android', agents.android, 5, 'Android'],
  ];
  for (const [name, agent, touch, first] of cases) {
    it(`puts ${name} first with the primary button and keeps the rest secondary`, async () => {
      asVisitor(agent, touch);
      vi.mocked(request).mockResolvedValue({ items: allAvailable });
      view(<DownloadsPage />);
      await screen.findByRole('link', { name: `Download for ${first}` });
      expect(titles()[0]).toBe(first);
      const primary = screen.getAllByRole('link', { name: /^Download for/ }).filter((link) => link.classList.contains('primary'));
      expect(primary.map((link) => link.textContent)).toEqual([`Download for ${first}`]);
      const card = screen.getByRole('link', { name: `Download for ${first}` }).closest('article')!;
      expect(card).toHaveClass('is-featured');
      expect(within(card).getByText('Your system')).toBeInTheDocument();
      expect(document.querySelectorAll('.ac-download-card.is-featured')).toHaveLength(1);
    });
  }
  it('puts iOS first for an iPhone and an iPad in desktop mode', async () => {
    for (const [agent, touch] of [[agents.iphone, 5], [agents.macos, 5]] as const) {
      cleanup(); vi.restoreAllMocks(); asVisitor(agent, touch);
      vi.mocked(request).mockResolvedValue({ items: [...allAvailable, file({ platform: 'ios', available: true, version: '0.2.0', url: 'https://apps.apple.com/app/id123' })] });
      view(<DownloadsPage />);
      const store = await screen.findByRole('link', { name: 'Open App Store' });
      expect(store).toHaveClass('primary');
      const ios = store.closest('.ac-ios')!;
      expect(ios).toHaveClass('is-featured');
      expect(ios.compareDocumentPosition(document.querySelector('.ac-download-grid')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(screen.getAllByRole('link', { name: /^Download for/ }).some((link) => link.classList.contains('primary'))).toBe(false);
      expect(titles()[0]).toBe('Windows');
    }
  });
  it('keeps the usual order with Windows featured for an unknown system', async () => {
    asVisitor(agents.chromeos);
    vi.mocked(request).mockResolvedValue({ items: allAvailable });
    view(<DownloadsPage />);
    await screen.findByRole('link', { name: 'Download for Windows' });
    expect(titles()).toEqual(['Windows', 'macOS', 'Linux', 'Android']);
    expect(screen.getByRole('link', { name: 'Download for Windows' })).toHaveClass('primary');
    expect(screen.getByText('Desktop')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Download for Android' })).not.toHaveClass('primary');
    expect(document.querySelector('.ac-ios')!.compareDocumentPosition(document.querySelector('.ac-download-grid')!) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });
  it('explains Android installation near the Android card in both languages', async () => {
    vi.mocked(request).mockResolvedValue({ items: allAvailable });
    view(<DownloadsPage />);
    const hint = await screen.findByText('After downloading, open the file and allow installation from this source.');
    expect(hint.closest('article')).toHaveAttribute('data-platform', 'android');
    cleanup(); app.lang = 'ru';
    view(<DownloadsPage />);
    expect(await screen.findByText('После скачивания откройте файл и разрешите установку из этого источника.')).toBeInTheDocument();
  });
});

describe('own password and sign-out everywhere', () => {
  it('changes a member password without a 2FA code and reports the result', async () => {
    app.user.role = 'member';
    vi.mocked(request).mockImplementation(async (path: string) => (path === '/api/me/devices' ? devicesInfo : { status: 'ok' }));
    view(<DevicesPage />, '/devices');
    fireEvent.click(await screen.findByRole('button', { name: 'Change password' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).queryByLabelText('Your current 2FA code')).toBeNull();
    fireEvent.change(within(dialog).getByLabelText('New password'), { target: { value: 'short' } });
    fireEvent.change(within(dialog).getByLabelText('Current password'), { target: { value: 'old-password-123' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change password' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('12–128');
    fireEvent.change(within(dialog).getByLabelText('New password'), { target: { value: 'new-password-1234' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change password' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/me/password', { method: 'POST', body: { current_password: 'old-password-123', new_password: 'new-password-1234' } }));
    expect(await screen.findByRole('status')).toHaveTextContent('Password changed. Other sign-ins have ended.');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
  it('keeps the dialog with an error when the current password is wrong', async () => {
    app.user.role = 'member';
    vi.mocked(request).mockImplementation(async (path: string) => {
      if (path === '/api/me/devices') return devicesInfo;
      throw new ApiError(400, 'invalid_password');
    });
    view(<DevicesPage />, '/devices');
    fireEvent.click(await screen.findByRole('button', { name: 'Change password' }));
    fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'wrong-password-1' } });
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'new-password-1234' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('The current password is incorrect.')).toBeInTheDocument();
    expect(screen.getByLabelText('Current password')).toHaveValue('');
  });
  it('asks an administrator for the 2FA code to sign out everywhere', async () => {
    vi.mocked(request).mockImplementation(async (path: string) => (path === '/api/me/devices' ? devicesInfo : { status: 'ok' }));
    view(<DevicesPage />, '/devices');
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out everywhere' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Sign out everywhere' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('six-digit');
    fireEvent.change(within(dialog).getByLabelText('Your current 2FA code'), { target: { value: '123456' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Sign out everywhere' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/me/sign-out-everywhere', { method: 'POST', body: { code: '123456' } }));
    expect(await screen.findByRole('status')).toHaveTextContent('This browser stays signed in.');
  });
  it('shows how many new app devices were added in the window', async () => {
    vi.mocked(request).mockResolvedValue(devicesInfo);
    view(<DevicesPage />, '/devices');
    expect(await screen.findByText('New devices in 30 days: 1 of 3')).toBeInTheDocument();
    cleanup(); app.lang = 'ru';
    vi.mocked(request).mockResolvedValue({ ...devicesInfo, device_changes: { used: 2, limit: 3, days: 21 } });
    view(<DevicesPage />, '/devices');
    expect(await screen.findByText('Новых устройств за 21 день: 2 из 3')).toBeInTheDocument();
  });
});

describe('deleting members and invitations', () => {
  it('shows password sign-in for members and 2FA only for administrators', async () => {
    vi.mocked(request).mockResolvedValue({ items: [{ ...member, totp_enabled: false }, app.user, { ...app.user, id: 9, email: 'new-admin@example.com', display_name: 'New Admin', totp_enabled: false }], total: 3 });
    view(<MembersPage />, '/admin/members');
    await screen.findByText('Member One');
    expect(screen.getByText('Password sign-in')).toBeInTheDocument();
    expect(screen.getByText('2FA enabled')).toBeInTheDocument();
    expect(screen.getByText('2FA not configured')).toBeInTheDocument();
  });
  it('deletes a member only with a 2FA code and never offers it on the own card', async () => {
    let deleted = false;
    vi.mocked(request).mockImplementation(async (path: string, options) => {
      if (options?.method === 'POST') { deleted = true; return undefined; }
      if (path.endsWith('/devices')) return devicesInfo;
      return { items: deleted ? [app.user] : [member, app.user], total: deleted ? 1 : 2 };
    });
    view(<MembersPage />, '/admin/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Details: Admin' }));
    expect(screen.queryByRole('button', { name: 'Delete member' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Details: Member One' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete member' }));
    expect(screen.getByText(/This cannot be undone/)).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete member' }));
    expect(within(screen.getByRole('dialog')).getByRole('alert')).toHaveTextContent('six-digit');
    fireEvent.change(screen.getByLabelText('Your current 2FA code'), { target: { value: '123456' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete member' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/admin/members/2/delete', { method: 'POST', body: { code: '123456' } }));
    await waitFor(() => expect(screen.queryByText('Member One')).toBeNull());
  });
  it('deletes a used invitation and offers revoke only for an active one', async () => {
    const used = { ...invite, id: 4, email: 'used@example.com', used_at: '2026-01-02T00:00:00Z' };
    vi.mocked(request).mockImplementation(async (_path, options) => (options?.method === 'POST' ? undefined : { items: [invite, used], total: 2 }));
    view(<InvitesPage />, '/admin/invites');
    await screen.findByText('used@example.com');
    expect(screen.queryByRole('button', { name: 'Revoke: used@example.com' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Revoke: new@example.com' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Delete: used@example.com' }));
    expect(screen.getByRole('heading', { name: 'Delete invitation' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Your current 2FA code'), { target: { value: '654321' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/admin/invites/4/delete', { method: 'POST', body: { code: '654321' } }));
  });
});
