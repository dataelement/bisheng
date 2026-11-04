/** 两端共享的传输与交互约束。这里的状态不能授予身份或业务权限。 */
export type KunlianLogoutAction = { kind: 'kunlian_logout'; method: 'POST'; url: '/api/kunlian/logout'; ticket: string };
export type KunlianLogoutResult = { auth_source: 'kunlian'; local_logged_out: true; next_action: KunlianLogoutAction | null };
export const KUNLIAN_CSRF_PATH = '/api/v1/identity-integrations/kunlian/session/csrf';

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {};
}

const failures: Record<number, readonly [number, string]> = {
  19320: [400, 'LOGIN_INVALID'], 19321: [409, 'DIRECTORY_NOT_READY'], 19322: [403, 'IDENTITY_UNAVAILABLE'],
  19323: [401, 'SESSION_EXPIRED'], 19324: [503, 'DEPENDENCY_UNAVAILABLE'], 19325: [502, 'DIRECTORY_SYNC_FAILED'],
  19326: [409, 'SYNC_CONFLICT'], 19327: [409, 'BINDING_CONFLICT'], 19328: [403, 'TRUST_REJECTED'], 19329: [502, 'LOGOUT_INCOMPLETE'],
};

export function kunlianFailure(value: unknown, httpStatus: number | undefined): string | null {
  const body = record(value);
  const expected = typeof body.status_code === 'number' ? failures[body.status_code] : undefined;
  return expected && expected[0] === httpStatus && record(body.data).reason_code === expected[1] ? expected[1] : null;
}

export function safeKunlianReturnTo(raw: string): string {
  const control = Array.from(raw).some(char => char === '\\' || char.charCodeAt(0) < 32 || (char.charCodeAt(0) >= 127 && char.charCodeAt(0) <= 159));
  if (raw.length > 2048 || !raw.startsWith('/') || raw.startsWith('//') || control
      || /%(?:00|0a|0d|25|2f|5c)/i.test(raw) || raw.includes('#')) return '/';
  try {
    const path = decodeURIComponent(raw.split('?')[0]);
    if (path.includes('//') || path.split('/').some(part => part === '.' || part === '..')) return '/';
    const query = new URLSearchParams(raw.split('?').slice(1).join('?'));
    if (['ar', 'access_token', 'id_token', 'token', 't', 'code', 'state', 'ticket'].some(name => query.has(name))) return '/';
    return ['/', '/workspace', '/flow', '/build'].some(prefix => path === prefix || (prefix !== '/' && path.startsWith(prefix + '/'))) ? raw : '/';
  } catch { return '/'; }
}

export function kunlianLoginUrl(raw = `${location.pathname}${location.search}`): string {
  return `/api/oauth2/kunlian?return_to=${encodeURIComponent(safeKunlianReturnTo(raw))}`;
}

export function isBrowserIdentityUrl(raw: string): boolean {
  try {
    const url = new URL(raw, location.origin);
    if (['/api/v1/user/login', '/api/v1/user/regist', '/api/v1/user/public_key', '/api/v1/user/get_captcha', '/api/v1/env'].includes(url.pathname)) return false;
    return url.origin === location.origin && url.pathname.startsWith('/api/')
      && !/^\/api\/(?:v[23](?:\/|$)|dsh(?:\/|$)|v1\/(?:internal|dsh)(?:\/|$))/.test(url.pathname);
  } catch { return false; }
}

/** 仅记住本页应选择的协议。服务器仍独立验证每次请求。 */
export class KunlianBrowserFlow {
  private expected = false;
  private confirmed = false;
  private sourceKnown = false;
  private manualLoginRequired = false;
  private redirecting = false;
  private notices = new Map<string, number>();

  constructor() {
    if (typeof location !== 'undefined' && location.hash === '#kunlian-login') {
      this.expected = true;
      this.clearLocalHints();
      history.replaceState(history.state, '', `${location.pathname}${location.search}`);
    }
  }

  isKunlian(): boolean { return this.expected || this.confirmed; }

  confirmUser(user: unknown): boolean {
    const kunlian = record(user).auth_source === 'kunlian';
    if (this.expected && !kunlian) { this.manualLoginRequired = true; return false; }
    this.confirmed = kunlian;
    this.sourceKnown = true;
    this.expected = false;
    this.manualLoginRequired = false;
    if (kunlian) this.clearLocalHints();
    return true;
  }

  observeFailure(reason: string): void {
    if (this.isKunlian() || reason === 'SESSION_EXPIRED') this.expected = true;
  }

  needsProtocolProbe(): boolean { return !this.sourceKnown && !this.expected; }
  expectLocalProtocol(): void { this.expected = true; }
  deferAutomaticLogin(): void { this.manualLoginRequired = true; }
  requiresManualLogin(): boolean { return this.manualLoginRequired; }
  resetAfterExplicitLogin(): void {
    this.expected = this.confirmed = this.sourceKnown = this.redirecting = this.manualLoginRequired = false;
  }

  shouldPresent(reason: string): boolean {
    const now = Date.now(), previous = this.notices.get(reason);
    if (previous !== undefined && now - previous < 5000) return false;
    this.notices.set(reason, now);
    return true;
  }

  reauthorize(): void {
    if (this.redirecting) return;
    this.redirecting = true;
    this.clearLocalHints();
    location.href = kunlianLoginUrl();
  }

  validateLogout(value: unknown): value is KunlianLogoutResult {
    const result = record(value);
    if (result.auth_source !== 'kunlian') {
      if (this.isKunlian()) throw new Error('KUNLIAN_LOCAL_LOGOUT_UNCONFIRMED');
      return false;
    }
    if (result.local_logged_out !== true || !Object.hasOwn(result, 'next_action')) throw new Error('KUNLIAN_LOCAL_LOGOUT_UNCONFIRMED');
    if (result.next_action !== null) {
      const action = record(result.next_action);
      if (Object.keys(action).sort().join(',') !== 'kind,method,ticket,url' || action.kind !== 'kunlian_logout'
          || action.method !== 'POST' || action.url !== '/api/kunlian/logout' || typeof action.ticket !== 'string'
          || !/^[A-Za-z0-9_-]{22,512}$/.test(action.ticket)) throw new Error('KUNLIAN_LOGOUT_ACTION_INVALID');
    }
    return true;
  }

  completeLogout(value: unknown): boolean {
    if (!this.validateLogout(value)) return false;
    this.clearLocalHints();
    if (value.next_action === null) { location.href = '/'; return true; }
    const form = document.createElement('form');
    form.method = 'POST'; form.action = '/api/kunlian/logout'; form.hidden = true;
    const ticket = document.createElement('input');
    ticket.type = 'hidden'; ticket.name = 'ticket'; ticket.value = value.next_action.ticket;
    form.appendChild(ticket); document.body.appendChild(form); form.submit();
    return true;
  }

  private clearLocalHints(): void {
    try {
      for (const key of ['ws_token', 'UUR_INFO', 'isLogin', 'bs:auth-state', 'LOGIN_PATHNAME', 'LOGIN_PATHNAME_AT']) localStorage.removeItem(key);
    } catch { /* 浏览器拒绝存储不影响服务器鉴权。 */ }
  }
}
