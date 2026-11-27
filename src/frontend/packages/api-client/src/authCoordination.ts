import { AuthSessionError, type AuthEnvironment, type AuthEvent } from './authTypes';

const LOCK_NAME = 'bisheng:platform-auth';
const LEASE_MS = 15000;
interface Lease { key: string; owner: string; fence: number; until: number }
let database: Promise<IDBDatabase> | undefined;
function openDatabase(): Promise<IDBDatabase> {
  database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open('bisheng-auth-coordination', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('leases', { keyPath: 'key' });
    request.onsuccess = () => {
      request.result.onversionchange = () => { request.result.close(); database = undefined; };
      resolve(request.result);
    };
    request.onblocked = () => { database = undefined; reject(new Error('Coordination database blocked')); };
    request.onerror = () => { database = undefined; reject(request.error); };
  });
  return database;
}
async function mutateLease(update: (lease: Lease | undefined) => Lease | undefined): Promise<Lease | undefined> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction('leases', 'readwrite');
    const store = transaction.objectStore('leases');
    const request = store.get(LOCK_NAME);
    let result: Lease | undefined;
    request.onsuccess = () => {
      result = update(request.result as Lease | undefined);
      if (result) store.put(result);
    };
    transaction.oncomplete = () => resolve(result);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}
/** An atomic IndexedDB lease is the fallback; localStorage is never a lock. */
export async function withAuthLock<T>(callback: (isCurrent: () => boolean) => Promise<T>): Promise<T> {
  if (typeof navigator !== 'undefined' && navigator.locks) {
    let entered = false;
    try {
      return await navigator.locks.request(LOCK_NAME, { mode: 'exclusive' }, () => { entered = true; return callback(() => true); });
    } catch (cause) { if (entered) throw cause; }
  }
  if (typeof indexedDB === 'undefined') throw new AuthSessionError(503, 10659, 'auth_service_unavailable', true);
  const owner = crypto.randomUUID();
  const deadline = Date.now() + 30000;
  let acquired: Lease | undefined;
  while (!acquired && Date.now() < deadline) {
    acquired = await mutateLease(lease => !lease || lease.until <= Date.now()
      ? { key: LOCK_NAME, owner, fence: (lease?.fence ?? 0) + 1, until: Date.now() + LEASE_MS }
      : undefined).catch(() => { throw new AuthSessionError(503, 10659, 'auth_service_unavailable', true); });
    if (!acquired) await new Promise(resolve => setTimeout(resolve, 75 + Math.random() * 100));
  }
  if (!acquired) throw new AuthSessionError(503, 10659, 'auth_service_unavailable', true);
  const fence = acquired.fence;
  let current = true;
  const renew = setInterval(() => {
    void mutateLease(lease => {
      if (lease?.owner !== owner || lease.fence !== fence || lease.until <= Date.now()) {
        current = false;
        return undefined;
      }
      acquired = { ...lease, until: Date.now() + LEASE_MS };
      return acquired;
    }).catch(() => { current = false; });
  }, LEASE_MS / 3);
  try { return await callback(() => current && Date.now() < (acquired?.until ?? 0)); }
  finally {
    current = false;
    clearInterval(renew);
    await mutateLease(lease => lease?.owner === owner && lease.fence === fence
      ? { ...lease, until: 0 } : undefined).catch(() => undefined);
  }
}

export function requestHostAuthRenewal(): void {
  const bridge = (window as unknown as { BishengMobile?: { postMessage?: (message: string) => void } }).BishengMobile;
  if (typeof bridge?.postMessage === 'function') {
    try { bridge.postMessage(JSON.stringify({ type: 'platform_auth_refresh_required' })); }
    catch { /* The host may already be closing; keep browser error handling active. */ }
  }
  window.dispatchEvent(new Event('bisheng:host-auth-required'));
}

export function browserAuthEnvironment(): AuthEnvironment {
  const listeners = new Set<(event: AuthEvent) => void>();
  let channel: BroadcastChannel | null = null;
  try { if (typeof BroadcastChannel !== 'undefined') channel = new BroadcastChannel(LOCK_NAME); }
  catch { /* Private browsing can disable this optional notification transport. */ }
  const receive = (value: unknown) => {
    if (!value || typeof value !== 'object') return;
    const event = value as AuthEvent;
    if (!['login', 'logout', 'refresh'].includes(event.type)) return;
    if (event.session !== null && (typeof event.session !== 'string' || !/^[a-f0-9]{32}$/.test(event.session))) return;
    listeners.forEach(listener => listener(event));
  };
  channel?.addEventListener('message', event => receive(event.data));
  window.addEventListener('storage', event => {
    if (event.key === LOCK_NAME && event.newValue) {
      try { receive(JSON.parse(event.newValue)); } catch { /* Untrusted notification. */ }
    }
  });
  return {
    now: Date.now,
    hostOwned: () => typeof (window as unknown as { BishengMobile?: { postMessage?: unknown } }).BishengMobile?.postMessage === 'function',
    requestHostRenewal: requestHostAuthRenewal,
    selectedSession: () => document.cookie.split('; ').find(cookie => cookie.startsWith('platform_session_hint='))?.split('=')[1] ?? null,
    selectSession: (session, cookieRetentionSeconds = 10454400) => {
      if (session && !/^[a-f0-9]{32}$/.test(session)) throw new Error('Invalid session selector');
      document.cookie = `platform_session_hint=${session ?? ''}; Path=/; SameSite=Lax; Max-Age=${session ? cookieRetentionSeconds : 0}${location.protocol === 'https:' ? '; Secure' : ''}`;
    },
    clearLegacyAuth: () => {
      for (const key of ['ws_token', 'isLogin', 'UUR_INFO', 'bs:auth-state']) {
        try { localStorage.removeItem(key); } catch { /* Storage can be disabled. */ }
      }
    },
    lock: withAuthLock,
    publish: event => {
      channel?.postMessage(event);
      if (!channel) {
        try { localStorage.setItem(LOCK_NAME, JSON.stringify({ ...event, nonce: crypto.randomUUID() })); }
        catch { /* Notifications do not provide mutual exclusion. */ }
      }
    },
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
  };
}
