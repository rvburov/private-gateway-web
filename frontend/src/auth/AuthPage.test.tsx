import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthPage } from './AuthPage';
import { ApiError } from '../api/client';

const mocked = vi.hoisted(() => ({ request: vi.fn(), setUser: vi.fn(), lang: 'en' as 'en' | 'ru' }));
vi.mock('../api/client', () => ({ request: mocked.request, ApiError: class extends Error { constructor(public status: number, public code: string, public retryAfter?: number) { super(code); } } }));
vi.mock('../app/context', () => ({ useApp: () => ({ lang: mocked.lang, user: null, setUser: mocked.setUser }) }));
vi.mock('../ui', () => ({ Icon: () => <svg />, LanguageSwitch: () => <div />, ThemeButton: () => <button type="button">Theme</button> }));
const user = { id: 1, email: 'member@example.test', display_name: 'Member', role: 'member', status: 'active', totp_enabled: true, created_at: '2026-11-09T00:00:00Z' };
function show(path = '/login') { return render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/downloads" element={<h1>Downloads page</h1>} /><Route path="*" element={<AuthPage />} /></Routes></MemoryRouter>); }
function enterPassword() { fireEvent.change(screen.getByLabelText('Email'), { target: { value: user.email } }); fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password-123' } }); }
function enterOtp() { fireEvent.change(screen.getByLabelText('Digit 1 of 6'), { target: { value: '345678' } }); }
beforeEach(() => { mocked.request.mockReset(); mocked.setUser.mockReset(); mocked.lang = 'en'; });

describe('real authentication flow', () => {
  it('validates input and never authenticates without a server response', async () => {
    show(); fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByRole('alert')).toHaveTextContent('valid email'); expect(mocked.request).not.toHaveBeenCalled();
    enterPassword(); mocked.request.mockRejectedValue(new ApiError(401, 'invalid_credentials'));
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' })); await screen.findByText('Email or password is incorrect.');
    expect(screen.getByLabelText('Password')).toHaveValue(''); expect(mocked.setUser).not.toHaveBeenCalled();
  });
  it('completes password and OTP with the remembered-device choice', async () => {
    mocked.request.mockResolvedValueOnce({ status: 'totp_required', user: null }).mockResolvedValueOnce({ status: 'ok', user });
    show(); enterPassword(); fireEvent.click(screen.getByRole('checkbox', { name: /Remember this device/ })); fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByRole('heading', { name: 'Confirm your sign-in' }); enterOtp(); fireEvent.click(screen.getByRole('button', { name: 'Open account' }));
    await screen.findByRole('heading', { name: 'Downloads page' });
    expect(mocked.request).toHaveBeenNthCalledWith(1, '/api/auth/login', { method: 'POST', body: { email: user.email, password: 'test-password-123' } });
    expect(mocked.request).toHaveBeenNthCalledWith(2, '/api/auth/2fa', { method: 'POST', body: { code: '345678', remember_device: true } }); expect(mocked.setUser).toHaveBeenCalledWith(user);
  });
  it('sends a recovery code and restarts an expired sign-in step', async () => {
    mocked.request.mockResolvedValueOnce({ status: 'totp_required', user: null }).mockRejectedValueOnce(new ApiError(401, 'login_expired'));
    show(); enterPassword(); fireEvent.click(screen.getByRole('button', { name: 'Sign in' })); await screen.findByRole('heading', { name: 'Confirm your sign-in' });
    fireEvent.click(screen.getByRole('button', { name: 'Use a recovery code' })); fireEvent.change(screen.getByLabelText('Recovery code'), { target: { value: 'ab12-cd34' } }); fireEvent.click(screen.getByRole('button', { name: 'Open account' }));
    await screen.findByRole('heading', { name: 'Sign in to Private Gateway' });
    expect(mocked.request).toHaveBeenLastCalledWith('/api/auth/2fa', { method: 'POST', body: { recovery_code: 'ab12-cd34', remember_device: false } }); expect(screen.getByRole('alert')).toHaveTextContent('expired');
  });
  it('shows actual server QR and holds the user until backup codes are saved', async () => {
    mocked.request.mockResolvedValueOnce({ status: 'totp_setup_required', user: null }).mockResolvedValueOnce({ secret: 'TESTONLY'.repeat(4), otpauth_uri: 'otpauth://totp/test', qr_svg: '<svg width="41" height="41"><path d="M1 1h5v5H1z"/></svg>' }).mockResolvedValueOnce({ status: 'ok', user, recovery_codes: ['test-code-one', 'test-code-two'] });
    show('/register'); fireEvent.change(screen.getByLabelText('Invitation code'), { target: { value: 'invitation-test' } }); fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Member' } }); fireEvent.change(screen.getByLabelText('Email from your invitation'), { target: { value: user.email } }); fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password-123' } }); fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findByRole('img', { name: 'QR code for your authenticator app' }); expect(screen.getByRole('img', { name: /QR code/ }).getAttribute('src')).toMatch(/^data:image\/svg\+xml/);
    enterOtp(); fireEvent.click(screen.getByRole('button', { name: 'Continue' })); await screen.findByRole('heading', { name: 'Recovery codes' }); expect(mocked.setUser).not.toHaveBeenCalled(); expect(screen.getByText('test-code-one')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Go to account' })); expect(screen.getByRole('alert')).toHaveTextContent('saved'); fireEvent.click(screen.getByRole('checkbox', { name: 'I have saved the recovery codes' })); fireEvent.click(screen.getByRole('button', { name: 'Go to account' }));
    await screen.findByRole('heading', { name: 'Downloads page' }); expect(mocked.setUser).toHaveBeenCalledWith(user);
  });
  it('restarts an expired setup challenge instead of leaving a stale QR step', async () => {
    mocked.request.mockResolvedValueOnce({ status: 'totp_setup_required', user: null }).mockRejectedValueOnce(new ApiError(401, 'login_expired'));
    show(); enterPassword(); fireEvent.click(screen.getByRole('button', { name: 'Sign in' })); await screen.findByText('This sign-in step has expired. Enter your email and password again.'); expect(screen.getByRole('heading', { name: 'Sign in to Private Gateway' })).toBeVisible();
  });
  it('submits administrator reset code and shows a completed reset', async () => {
    mocked.request.mockResolvedValue({ status: 'ok' }); show('/reset'); fireEvent.change(screen.getByLabelText('Email'), { target: { value: user.email } }); fireEvent.change(screen.getByLabelText('Administrator code'), { target: { value: 'reset-test' } }); fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'replacement-password-123' } }); fireEvent.click(screen.getByRole('button', { name: 'Update password' }));
    await screen.findByRole('heading', { name: 'Password updated' }); expect(mocked.request).toHaveBeenCalledWith('/api/auth/reset', { method: 'POST', body: { email: user.email, code: 'reset-test', new_password: 'replacement-password-123' } }); expect(mocked.setUser).not.toHaveBeenCalled();
  });
  it('disables retries during a server rate-limit interval', async () => {
    mocked.request.mockRejectedValue(new ApiError(429, 'rate_limited', 45)); show(); enterPassword(); fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()); expect(screen.getByRole('status')).toHaveTextContent('45 seconds');
  });
});
