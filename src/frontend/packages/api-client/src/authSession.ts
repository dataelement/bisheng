import { browserAuthEnvironment } from './authCoordination';
import { AuthSessionError, type AuthEvent, type AuthEnvironment, type AuthSessionMetadata, type AuthTransport, type PlatformLoginInput } from './authTypes';

const PREFIX = '/api/v1/auth/';
const EARLY_REFRESH_MS = 86400000;
export const isPlatformAuthPath = (url: string): boolean => /\/api\/v1\/auth\//.test(url);
function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}
export function authFailureCode(value: unknown): number {
  const root = object(value);
  return Number(root.status_code ?? root.code ?? object(object(root.response).data).status_code ?? 0);
}
export function isAccessExpired(value: unknown): boolean { return authFailureCode(value) === 10651; }
export function isDefinitiveAuthFailure(value: unknown): boolean {
  const code = authFailureCode(value);
  return code >= 10650 && code <= 10659 && code !== 10651 && code !== 10657 && code !== 10659;
}
function metadata(value: unknown): AuthSessionMetadata {
  const data = object(value);
  if (typeof data.session_id !== 'string' || !/^[a-f0-9]{32}$/.test(data.session_id)
    || !['cookie', 'native', 'host'].includes(String(data.refresh_mode))
    || !['PENDING_WEB_BIND', 'BOUND'].includes(String(data.delivery_state))
    || !Number.isFinite(Date.parse(String(data.access_expires_at)))
    || !Number.isFinite(Date.parse(String(data.session_expires_at)))) {
    throw new AuthSessionError(503, 10659, 'auth_service_unavailable', true);
  }
  return data as unknown as AuthSessionMetadata;
}
/** One controller for both SPAs. Credentials remain in HttpOnly cookies. */
export class BrowserAuthSession {
  snapshot: AuthSessionMetadata | null = null;
  hostPending = false;
  private epoch = 0;
  private initialized = false;
  private initialization?: Promise<AuthSessionMetadata | null>;
  private refreshing?: Promise<boolean>;
  private listeners = new Set<(event?: AuthEvent) => void>();
  private lastActivityRefresh = 0;
  private unsubscribe: () => void;
  constructor(private transport: AuthTransport, private environment: AuthEnvironment = browserAuthEnvironment()) {
    this.unsubscribe = environment.subscribe(event => {
      if (event.type === 'refresh') return;
      const selected = environment.selectedSession();
      if (event.type === 'login' && event.session !== selected) return;
      if (event.type === 'logout' && selected && event.session !== selected) return;
      this.epoch++;
      this.snapshot = null;
      this.hostPending = false;
      this.initialized = event.type === 'logout';
      this.emit(event);
    });
  }
  subscribe(listener: (event?: AuthEvent) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
  dispose(): void { this.unsubscribe(); this.listeners.clear(); }
  private emit(event?: AuthEvent): void { this.listeners.forEach(listener => listener(event)); }
  private async call(method: 'GET' | 'POST', endpoint: string, body?: unknown, csrf?: string, selector?: string | null): Promise<unknown> {
    let response;
    try { response = await this.transport(method, PREFIX + endpoint, body, csrf || selector ? { ...(csrf ? { 'X-CSRF-Token': csrf } : {}), ...(selector ? { 'X-Platform-Session': selector } : {}) } : undefined); }
    catch (cause) {
      if (cause instanceof AuthSessionError) throw cause;
      throw new AuthSessionError(0, 0, 'network_unavailable', true);
    }
    const envelope = object(response.data);
    const code = Number(envelope.status_code ?? response.status);
    if (response.status >= 400 || code !== 200) {
      const details = object(envelope.data);
      throw new AuthSessionError(response.status, code, String(details.auth_reason ?? 'authentication_failed'),
        response.status >= 500 || details.retryable === true);
    }
    return envelope.data;
  }
  private accept(value: unknown, epoch: number, isCurrent: () => boolean, selected: string | null, event?: 'login' | 'refresh'): AuthSessionMetadata | null {
    const session = metadata(value);
    if (epoch !== this.epoch || !isCurrent() || this.environment.selectedSession() !== selected) return null;
    this.snapshot = session;
    this.hostPending = false;
    this.initialized = true;
    if (session.refresh_mode === 'cookie') this.environment.selectSession(session.session_id, session.cookie_retention_seconds);
    this.emit(event ? { type: event, session: session.session_id } : undefined);
    if (event) this.environment.publish({ type: event, session: session.session_id });
    return session;
  }
  invalidate(): void { ++this.epoch; this.clear(); }
  private clear(): void {
    const selected = this.environment.selectedSession();
    this.hostPending = false;
    this.snapshot = null;
    this.initialized = true;
    this.environment.selectSession(null);
    this.environment.clearLegacyAuth();
    const event = { type: 'logout' as const, session: selected };
    this.emit(event);
    this.environment.publish(event);
  }
  /** Existing initialization is awaited by transports; providers own startup. */
  async settled(): Promise<void> { await this.initialization; }
  /** Always called on startup, before any identity-dependent query. */
  initialize(force = false): Promise<AuthSessionMetadata | null> {
    if (!force && this.initialized) return Promise.resolve(this.snapshot);
    this.initialization ??= this.environment.lock(async isCurrent => {
      const epoch = this.epoch;
      const selected = this.environment.selectedSession();
      try {
        let data;
        try { data = await this.call('GET', 'session'); }
        catch (cause) {
          if (!(cause instanceof AuthSessionError) || cause.code !== 10651) throw cause;
          if (this.environment.hostOwned?.() && selected) throw cause;
          const csrf = object(await this.call('GET', 'csrf')).csrf_token;
          data = await this.call('POST', 'refresh', {}, String(csrf ?? ''));
        }
        const session = metadata(data);
        const binding = session.delivery_state === 'PENDING_WEB_BIND';
        if (binding) {
          try { data = await this.call('POST', 'web-bootstrap', {}, session.csrf_token); }
          catch (cause) {
            if (!(cause instanceof AuthSessionError) || cause.code !== 10664) throw cause;
            if (selected !== session.session_id) throw new AuthSessionError(401, 10658, 'web_bootstrap_expired', false);
            const csrf = object(await this.call('GET', 'csrf')).csrf_token;
            data = await this.call('POST', 'refresh', {}, String(csrf ?? ''));
          }
        }
        return this.accept(data, epoch, isCurrent, selected, binding ? 'login' : undefined);
      } catch (cause) {
        if (cause instanceof AuthSessionError && !cause.retryable && cause.status === 401) {
          if (this.environment.hostOwned?.() && selected && epoch === this.epoch && isCurrent() && this.environment.selectedSession() === selected) {
            this.hostPending = true;
            this.initialized = true;
            this.environment.requestHostRenewal?.();
            this.emit();
            return null;
          }
          if (epoch === this.epoch && isCurrent() && this.environment.selectedSession() === selected) this.clear();
          return null;
        }
        throw cause;
      }
    }).finally(() => { this.initialization = undefined; });
    return this.initialization;
  }
  async login(input: PlatformLoginInput): Promise<AuthSessionMetadata | null> {
    const epoch = ++this.epoch;
    return this.environment.lock(async isCurrent => {
      const selected = this.environment.selectedSession();
      if (epoch !== this.epoch || !isCurrent()) return null;
      const data = await this.call('POST', 'login', { ...input, client_id: 'bisheng-web' });
      this.environment.clearLegacyAuth();
      return this.accept(data, epoch, isCurrent, selected, 'login');
    });
  }
  refresh(force = false): Promise<boolean> {
    if (this.hostPending || this.snapshot?.refresh_mode === 'host') return Promise.resolve(false);
    const observedExpiry = this.snapshot?.access_expires_at;
    this.refreshing ??= this.environment.lock(async isCurrent => {
      const epoch = this.epoch;
      const selected = this.environment.selectedSession();
      try {
        {
          try {
            const current = metadata(await this.call('GET', 'session'));
            if (current.refresh_mode === 'host') { this.accept(current, epoch, isCurrent, selected); return false; }
            if ((!force || current.access_expires_at !== observedExpiry) && Date.parse(current.access_expires_at) - this.environment.now() > EARLY_REFRESH_MS) {
              return Boolean(this.accept(current, epoch, isCurrent, selected));
            }
          } catch (cause) {
            if (!(cause instanceof AuthSessionError) || cause.code !== 10651) throw cause;
          }
        }
        if (epoch !== this.epoch || !isCurrent() || this.environment.selectedSession() !== selected) return false;
        const csrf = this.snapshot?.csrf_token || object(await this.call('GET', 'csrf')).csrf_token;
        let data;
        try { data = await this.call('POST', 'refresh', {}, String(csrf ?? '')); }
        catch (cause) {
          if (!(cause instanceof AuthSessionError) || cause.code !== 10660) throw cause;
          const recovered = object(await this.call('GET', 'csrf')).csrf_token;
          data = await this.call('POST', 'refresh', {}, String(recovered ?? ''));
        }
        return Boolean(this.accept(data, epoch, isCurrent, selected, 'refresh'));
      } catch (cause) {
        if (cause instanceof AuthSessionError && !cause.retryable && cause.status === 401 && epoch === this.epoch && isCurrent() && this.environment.selectedSession() === selected) this.clear();
        throw cause;
      }
    }).finally(() => { this.refreshing = undefined; });
    return this.refreshing;
  }
  async logout(all = false): Promise<void> {
    ++this.epoch;
    this.hostPending = false;
    const previous = this.environment.selectedSession();
    const csrf = this.snapshot?.csrf_token;
    const host = this.snapshot?.refresh_mode === 'host';
    const legacyHost = host && this.snapshot?.auth_source === 'legacy_dsh';
    this.snapshot = null;
    this.initialized = true;
    this.environment.selectSession(null);
    this.environment.publish({ type: 'logout', session: previous });
    this.emit({ type: 'logout', session: previous });
    try {
      await this.environment.lock(async () => {
        if (this.environment.selectedSession() && this.environment.selectedSession() !== previous) return;
        if (legacyHost) {
          const response = await this.transport('POST', '/api/v1/user/logout', {});
          if (response.status >= 400) throw new AuthSessionError(response.status, 10659, 'auth_service_unavailable', true);
          return;
        }
        const token = csrf || object(await this.call('GET', 'csrf', undefined, undefined, previous)).csrf_token;
        await this.call('POST', all ? 'logout-all' : 'logout', {}, String(token ?? ''), previous);
      });
    } finally {
      if (this.environment.selectedSession() === previous) this.environment.selectSession(null);
      this.environment.clearLegacyAuth();
    }
  }
  /** Refresh can extend Access after real activity; it never counts as activity. */
  noteBusinessActivity(): void {
    if (!this.snapshot || this.snapshot.refresh_mode !== 'cookie') return;
    const now = this.environment.now();
    if (now - this.lastActivityRefresh < 86400000 && Date.parse(this.snapshot.access_expires_at) - now > EARLY_REFRESH_MS) return;
    this.lastActivityRefresh = now;
    void this.refresh(true).catch(() => undefined);
  }
}
