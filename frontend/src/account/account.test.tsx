import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { request, ApiError } from '../api/client';
import { AccountLayout, DownloadsPage, InvitesPage, MembersPage } from './index';
import { inviteStatus, personName, safeDownloadUrl, type Download, type Invite, type User } from './types';

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
beforeEach(() => {
  cleanup();
  vi.mocked(request).mockReset();
  app.user.role = 'admin';
  app.lang = 'en';
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
