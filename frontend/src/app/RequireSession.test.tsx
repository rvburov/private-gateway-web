import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireSession } from './App';
import type { User } from '../api/types';

const state = {
  lang: 'en', user: null as User | null, loading: false, sessionError: null as unknown,
  reloadUser: vi.fn(),
};
vi.mock('./context', () => ({ useApp: () => state }));

function page(admin = false) {
  return render(<MemoryRouter initialEntries={['/protected']}><Routes>
    <Route path="/protected" element={<RequireSession admin={admin}><p>Protected content</p></RequireSession>} />
    <Route path="/login" element={<p>Sign-in route</p>} />
    <Route path="/downloads" element={<p>Downloads route</p>} />
  </Routes></MemoryRouter>);
}

describe('session and role routing', () => {
  beforeEach(() => { state.user = null; state.loading = false; state.sessionError = null; });
  it('waits for the real session before deciding access', () => {
    state.loading = true;
    page();
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    expect(screen.queryByText('Sign-in route')).not.toBeInTheDocument();
  });
  it('redirects unauthenticated visitors', () => {
    page();
    expect(screen.getByText('Sign-in route')).toBeInTheDocument();
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
  });
  it('does not expose administrator content to an ordinary member', () => {
    state.user = { id: 1, email: 'member@example.test', display_name: 'Synthetic', role: 'member', status: 'active', totp_enabled: true, created_at: '2026-01-01T00:00:00Z' };
    page(true);
    expect(screen.getByText('Downloads route')).toBeInTheDocument();
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
  });
  it('allows an active administrator', () => {
    state.user = { id: 2, email: 'admin@example.test', display_name: 'Synthetic', role: 'admin', status: 'active', totp_enabled: true, created_at: '2026-01-01T00:00:00Z' };
    page(true);
    expect(screen.getByText('Protected content')).toBeInTheDocument();
  });
  it('offers a retry on an unavailable API instead of pretending the user is signed out', () => {
    state.sessionError = new Error('Synthetic network failure');
    page();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(state.reloadUser).toHaveBeenCalledOnce();
    expect(screen.queryByText('Sign-in route')).not.toBeInTheDocument();
  });
});
