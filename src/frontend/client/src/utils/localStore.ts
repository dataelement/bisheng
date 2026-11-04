import { useSyncExternalStore } from 'react';

/**
 * A tiny localStorage-backed store for per-browser UI preferences and front-end-only
 * mock data (things the backend has no model for yet). Readable from any component via
 * `useLocalStore`; writes notify every subscriber, and other tabs through the `storage`
 * event. Not a replacement for server state — anything the backend owns stays in
 * react-query.
 */
export interface LocalStore<T> {
  get: () => T;
  set: (next: T | ((prev: T) => T)) => void;
  subscribe: (listener: () => void) => () => void;
}

export function createLocalStore<T>(key: string, fallback: T, parse: (raw: unknown) => T): LocalStore<T> {
  // The snapshot must keep its identity between writes (useSyncExternalStore contract),
  // so the parsed value is cached and only re-read after a cross-tab change.
  let cached = fallback;
  let loaded = false;
  const listeners = new Set<() => void>();

  const read = (): T => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : parse(JSON.parse(raw));
    } catch {
      return fallback;
    }
  };

  const get = (): T => {
    if (!loaded) {
      cached = read();
      loaded = true;
    }
    return cached;
  };

  const set = (next: T | ((prev: T) => T)) => {
    cached = typeof next === 'function' ? (next as (prev: T) => T)(get()) : next;
    loaded = true;
    try {
      localStorage.setItem(key, JSON.stringify(cached));
    } catch {
      // Storage unavailable (private mode / quota): the value still lives for this session.
    }
    listeners.forEach((listener) => listener());
  };

  const handleStorage = (event: StorageEvent) => {
    if (event.key !== key) return;
    loaded = false;
    listeners.forEach((listener) => listener());
  };

  const subscribe = (listener: () => void) => {
    if (listeners.size === 0) window.addEventListener('storage', handleStorage);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) window.removeEventListener('storage', handleStorage);
    };
  };

  return { get, set, subscribe };
}

export function useLocalStore<T>(store: LocalStore<T>): T {
  return useSyncExternalStore(store.subscribe, store.get);
}
