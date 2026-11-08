import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AppProvider, useApp } from './context';
import type { User } from '../api/types';

const user: User = { id: 1, email: 'member@example.test', display_name: 'Synthetic', role: 'member', status: 'active', totp_enabled: true, created_at: '2026-01-01T00:00:00Z' };

function Probe() {
  const context = useApp();
  return <><p data-testid="identity">{context.user?.email ?? 'anonymous'}</p><p data-testid="loading">{String(context.loading)}</p><button onClick={() => context.setUser(user)}>Complete login</button><button onClick={() => context.setUser(null)}>Complete logout</button></>;
}

describe('session request generations', () => {
  let finish: (response: Response) => void;
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>(resolve => { finish = resolve; })));
  });
  it('does not let a delayed anonymous /me reply discard a newer successful login', async () => {
    render(<AppProvider><Probe /></AppProvider>);
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('button', { name: 'Complete login' }));
    await act(async () => { finish(new Response(JSON.stringify({ error: { code: 'unauthorized' } }), { status: 401 })); });
    expect(screen.getByTestId('identity')).toHaveTextContent(user.email);
    expect(screen.getByTestId('loading')).toHaveTextContent('false');
  });
  it('does not let a delayed authenticated /me reply undo a newer logout', async () => {
    render(<AppProvider><Probe /></AppProvider>);
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('button', { name: 'Complete login' }));
    fireEvent.click(screen.getByRole('button', { name: 'Complete logout' }));
    await act(async () => { finish(new Response(JSON.stringify(user), { status: 200 })); });
    expect(screen.getByTestId('identity')).toHaveTextContent('anonymous');
    expect(screen.getByTestId('loading')).toHaveTextContent('false');
  });
});
