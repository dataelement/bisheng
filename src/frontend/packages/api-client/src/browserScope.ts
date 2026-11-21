function scopeError(message: string) {
  return Object.assign(new Error(message), {status_code: message === 'management_scope_changed' ? 19704 : 19705});
}

type ScopeProof = { scope_tenant_id: number; source?: string };

function validateProof(proof: ScopeProof): void {
  if (!proof || !Number.isSafeInteger(proof.scope_tenant_id) || proof.scope_tenant_id < 1)
    throw scopeError('management_scope_unavailable');
}

// Session establishment, discovery and control-plane roots must work without a selection.
// Business endpoints are deliberately NOT enumerated here: new API calls inherit
// browser context. Server route declarations remain the authorization authority.
const independentPaths = new Set([
  '/api/v1/user/info', '/api/v1/user/login', '/api/v1/user/logout',
  '/api/v1/user/public_key', '/api/v1/user/get_captcha', '/api/v1/user/regist',
  '/api/v1/user/sso', '/api/v1/user/switch-tenant',
  '/api/v1/user/change_password_public',
  '/api/v1/user/change_password', '/api/v1/user/avatar', '/api/v1/user/admin',
  '/api/v1/user/mark', '/api/v1/user/current-tenant', '/api/v1/user/tenants',
  '/api/v1/departments/get_user_primary_department',
  '/api/v1/admin/request-scope', '/api/v1/admin/request-scope/bootstrap',
  '/api/v1/admin/tenant-scope',
  '/api/v1/env', '/api/v1/web/config', '/api/v1/brand/runtime-config',
  '/api/v1/version', '/api/v1/all', '/api/v1/apps/_unavailable',
  '/api/user/me', '/api/config',
  '/api/v1/dsh/browser-config',
  '/api/v1/dsh/admin/settings',
]);

/** Browser transport boundary, independent of the generated route inventory. */
export function needsBrowserScope(method: string, raw: string, origin: string, baseURL = '/'): boolean {
  const base = new URL(baseURL.replace(/\/?$/, '/'), origin);
  const absolute = /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(raw);
  const url = absolute ? new URL(raw, origin) : new URL(raw.replace(/^\//, ''), base);
  if (url.origin !== origin || !/^https?:$/.test(url.protocol)) return false;
  const pathname = base.pathname !== '/' && url.pathname.startsWith(base.pathname)
    ? '/' + url.pathname.slice(base.pathname.length) : url.pathname;
  const path = pathname.replace(/^\/workspace(?=\/api\/)/, '').replace(/\/$/, '');
  if (!path.startsWith('/api/') || independentPaths.has(path)) return false;
  if (/^\/api\/v1\/(?:tenants|settings|org-sync|brand|commercial-licenses|me)(?:\/|$)/.test(path)) return false;
  if (path.startsWith('/api/v1/user/profile/')) return false;
  // These namespaces establish their own public, device or external credential.
  if (/^\/api\/(?:auth|oauth2|share|dsh|v2|v3)(?:\/|$)/.test(path)) return false;
  if (/^\/api\/v1\/(?:public|internal|share_link)(?:\/|$)/.test(path)) return false;
  if (method.toUpperCase() === 'GET' &&
      (path === '/api/v1/dsh/market/admin/plugins' || path === '/api/v1/dsh/market/admin/workbenches')) return true;
  if (/^\/api\/v1\/dsh(?:\/|$)/.test(path) && !/^\/api\/v1\/dsh\/admin(?:\/|$)/.test(path)) return false;
  return true;
}

/** An explicit shared-link credential owns its scope, even on a business URL. */
export function hasIndependentScope(headers?: object): boolean {
  return Object.entries(headers ?? {}).some(([key, value]) => key.toLowerCase() === 'share-token' && !!value);
}

export function isScopeReconfirmationChange(error: unknown): boolean {
  return typeof error === 'object' && error !== null &&
    'scopeReconfirmationChanged' in error && error.scopeReconfirmationChanged === true;
}

/** In-memory confirmed preference only; storage is a change notification, never authority. */
export class BrowserScopeSession {
  tenant: number | null = null;
  source: string | null = null;
  private pending: Promise<ScopeProof> | null = null;
  private recovery: Promise<ScopeProof> | null = null;
  private paused = false;
  private switching = 0;
  private lastTenant: number | null = null;

  get isPaused() { return this.paused; }

  accept(proof: ScopeProof): ScopeProof {
    validateProof(proof);
    this.pending = null;
    this.recovery = null;
    this.tenant = proof.scope_tenant_id;
    this.lastTenant = proof.scope_tenant_id;
    this.source = proof.source ?? null;
    this.paused = false;
    return proof;
  }

  pause() {
    this.paused = true;
    this.tenant = null;
    this.pending = null;
    this.recovery = null;
  }

  beginSwitch(): () => void {
    this.switching++;
    this.pause();
    let finished = false;
    return () => { if (!finished) { finished = true; this.switching--; } };
  }

  /** Only an explicit, authenticated server confirmation may recover a pause. */
  async reconfirm(load: () => Promise<ScopeProof>): Promise<ScopeProof> {
    if (this.switching) throw scopeError('management_scope_unavailable');
    if (!this.recovery) {
      this.pause();
      const recovery = Promise.resolve().then(load).then(proof => {
        if (this.recovery !== recovery) throw scopeError('management_scope_changed');
        validateProof(proof);
        if (this.lastTenant !== null && proof.scope_tenant_id !== this.lastTenant) {
          // Never submit an old page's action against a newly selected tenant.
          throw Object.assign(scopeError('management_scope_changed'), {scopeReconfirmationChanged: true});
        }
        return this.accept(proof);
      }).catch((error: unknown) => {
        if (this.recovery === recovery) this.pause();
        throw error;
      });
      this.recovery = recovery;
    }
    return this.recovery;
  }

  reset() {
    this.pause();
    this.paused = false;
    this.source = null;
    this.lastTenant = null;
  }

  async ensure(load: () => Promise<ScopeProof>): Promise<ScopeProof> {
    if (this.paused) throw scopeError('management_scope_unavailable');
    if (this.tenant !== null) return { scope_tenant_id: this.tenant, source: this.source ?? undefined };
    if (!this.pending) {
      const pending = Promise.resolve().then(load).then(proof => {
        if (this.paused || this.pending !== pending) throw scopeError('management_scope_changed');
        return this.accept(proof);
      }).catch((error: unknown) => {
        if (this.pending === pending) this.pause();
        throw error;
      });
      this.pending = pending;
    }
    return this.pending;
  }
}
