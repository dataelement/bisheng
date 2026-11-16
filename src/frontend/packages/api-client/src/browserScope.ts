import routes from './requestScopeRoutes.json';
import gatewayRoutes from './gatewayRequestScopeRoutes.json';

function scopeError(message: string) {
  return Object.assign(new Error(message), {status_code: message === 'management_scope_changed' ? 19704 : 19705});
}

type ScopeProof = { scope_tenant_id: number; source?: string };
const patterns = [...routes, ...gatewayRoutes].map(row => ({
  ...row,
  pattern: new RegExp('^' + row.path.split(/(\{[^}]+\})/).map(part =>
    part.startsWith('{') ? (part.includes(':path') ? '.+' : '[^/]+') : part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
  ).join('') + '/?$'),
}));

/** Generated route order retains static-before-parameter dispatch semantics. */
export function requestScopeKind(method: string, raw: string, origin: string): string | null {
  const url = new URL(raw, origin);
  if (url.origin !== origin) return null;
  const path = url.pathname.replace(/^\/workspace(?=\/api\/)/, '');
  const route = patterns.find(row => row.method === method.toUpperCase() && row.pattern.test(path));
  if (!route) return null;
  if (route.variant && url.searchParams.get(route.variant[0]) === route.variant[1]) return route.variant[2];
  return route.scope;
}

export function needsBrowserScope(method: string, raw: string, origin: string): boolean {
  const kind = requestScopeKind(method, raw, origin);
  return kind === 'tenant' || kind === 'personal';
}

/** In-memory confirmed preference only; storage is a change notification, never authority. */
export class BrowserScopeSession {
  tenant: number | null = null;
  source: string | null = null;
  private pending: Promise<ScopeProof> | null = null;
  private paused = false;

  accept(proof: ScopeProof): ScopeProof {
    if (!Number.isSafeInteger(proof.scope_tenant_id) || proof.scope_tenant_id < 1) throw scopeError('management_scope_unavailable');
    this.pending = null;
    this.tenant = proof.scope_tenant_id;
    this.source = proof.source ?? null;
    this.paused = false;
    return proof;
  }

  pause() {
    this.paused = true;
    this.tenant = null;
    this.pending = null;
  }

  reset() {
    this.pause();
    this.paused = false;
    this.source = null;
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
