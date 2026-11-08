export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, public readonly retryAfter?: number) {
    super(code);
    this.name = 'ApiError';
  }
}

let csrf: string | undefined;
let csrfRequest: Promise<string> | undefined;

async function readError(response: Response): Promise<ApiError> {
  let code = 'server_error';
  try {
    const body: unknown = await response.json();
    if (body && typeof body === 'object' && 'error' in body) {
      const error = body.error;
      if (error && typeof error === 'object' && 'code' in error && typeof error.code === 'string') code = error.code;
    }
  } catch { /* Неполный ответ прокси не показывается как HTML в интерфейсе. */ }
  const seconds = Number(response.headers.get('Retry-After'));
  return new ApiError(response.status, code, Number.isFinite(seconds) && seconds > 0 ? seconds : undefined);
}

export function clearCsrf(): void {
  csrf = undefined;
  csrfRequest = undefined;
}

async function csrfToken(): Promise<string> {
  if (csrf) return csrf;
  if (!csrfRequest) {
    csrfRequest = (async () => {
      const response = await fetch('/api/auth/csrf', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' });
      if (!response.ok) throw await readError(response);
      const data: { csrf_token?: unknown } = await response.json();
      if (typeof data.csrf_token !== 'string' || !data.csrf_token) throw new ApiError(502, 'server_error');
      csrf = data.csrf_token;
      return csrf;
    })().finally(() => { csrfRequest = undefined; });
  }
  return csrfRequest;
}

export async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  if (!path.startsWith('/api/') || path.includes('://')) throw new Error('Only relative API paths are allowed');
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET' && method !== 'HEAD') headers['X-CSRF-Token'] = await csrfToken();
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(path, { method, credentials: 'include', headers, cache: 'no-store',
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}) });
  } catch {
    throw new ApiError(0, 'network_error');
  }
  if (!response.ok) {
    const error = await readError(response);
    if (error.code === 'csrf_failed') {
      // Повтор мутации без явного действия пользователя исключен.
      clearCsrf();
      void csrfToken().catch(() => undefined);
    }
    // /me обрабатывается провайдером с номером запроса: запоздавшая проверка не
    // должна сбросить сеанс, который пользователь уже открыл новым входом.
    if (response.status === 401 && path !== '/api/me' && !path.startsWith('/api/auth/')) window.dispatchEvent(new Event('pg-session-expired'));
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
