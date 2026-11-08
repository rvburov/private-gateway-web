import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, clearCsrf, request } from './client';

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

describe('API request boundary', () => {
  beforeEach(clearCsrf);
  afterEach(() => { vi.unstubAllGlobals(); });

  it('obtains one CSRF token for concurrent mutations and sends cookie credentials', async () => {
    const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith('/csrf') ? json({ csrf_token: 'synthetic-csrf' }) : json({ status: 'ok' })));
    vi.stubGlobal('fetch', fetcher);
    await Promise.all([request('/api/auth/login', { method: 'POST', body: { email: 'one@example.test' } }), request('/api/auth/login', { method: 'POST', body: { email: 'two@example.test' } })]);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/csrf'))).toHaveLength(1);
    for (const [, options] of fetcher.mock.calls.slice(1)) {
      expect(options.credentials).toBe('include');
      expect(options.headers['X-CSRF-Token']).toBe('synthetic-csrf');
      expect(options.headers['Content-Type']).toBe('application/json');
    }
  });

  it('refreshes a rejected token but never repeats a mutation automatically', async () => {
    const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith('/csrf') ? json({ csrf_token: 'new-synthetic-csrf' }) : json({ error: { code: 'csrf_failed' } }, 403)));
    vi.stubGlobal('fetch', fetcher);
    await expect(request('/api/admin/invites', { method: 'POST', body: {} })).rejects.toMatchObject({ status: 403, code: 'csrf_failed' });
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/admin/invites')).toHaveLength(1);
  });

  it('signals revoked sessions on protected requests, without treating wrong passwords as expiry', async () => {
    const expired = vi.fn();
    window.addEventListener('pg-session-expired', expired);
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith('/csrf') ? json({ csrf_token: 'synthetic-csrf' }) : json({ error: { code: 'unauthorized' } }, 401))));
    await expect(request('/api/downloads')).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledOnce();
    await expect(request('/api/auth/login', { method: 'POST', body: {} })).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledOnce();
    window.removeEventListener('pg-session-expired', expired);
  });

  it('does not send credentials to an absolute URL', async () => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    await expect(request('https://example.test/api/me')).rejects.toThrow('relative API');
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('preserves retry information and ignores HTML error responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({ error: { code: 'rate_limited' } }, 429, { 'Retry-After': '30' })).mockResolvedValueOnce(new Response('<script>unsafe</script>', { status: 502 })));
    await expect(request('/api/me')).rejects.toMatchObject({ retryAfter: 30, code: 'rate_limited' });
    await expect(request('/api/me')).rejects.toMatchObject({ message: 'server_error' });
  });
});
