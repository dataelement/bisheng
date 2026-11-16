export const DSH_BROWSER_CONFIG_QUERY_KEY = ['dsh-browser-config'] as const;

// Deployment and download addresses are shared by all identities in this browser.
export const DSH_BROWSER_CONFIG_CACHE_OPTIONS = {
  staleTime: 5 * 60 * 1000,
  cacheTime: 30 * 60 * 1000,
  retry: false,
  retryOnMount: false,
  refetchOnMount: true,
  refetchOnWindowFocus: true,
  refetchInterval: false,
} as const;

const CHANGE_KEY = 'dsh-browser-config-changed';

export function notifyDshBrowserConfigChanged(): void {
  window.dispatchEvent(new Event(CHANGE_KEY));
  try {
    // Notify the other SPA and tabs on this origin without persisting settings.
    localStorage.setItem(CHANGE_KEY, `${Date.now()}:${Math.random()}`);
  } catch {
    // Same-tab invalidation still works when browser storage is disabled.
  }
}

/** Install once per application, rather than once per consuming component. */
export function subscribeDshBrowserConfigChanges(refresh: () => void): () => void {
  const handleStorage = (event: StorageEvent) => {
    if (event.key === CHANGE_KEY) refresh();
  };
  window.addEventListener(CHANGE_KEY, refresh);
  window.addEventListener('storage', handleStorage);
  return () => {
    window.removeEventListener(CHANGE_KEY, refresh);
    window.removeEventListener('storage', handleStorage);
  };
}
