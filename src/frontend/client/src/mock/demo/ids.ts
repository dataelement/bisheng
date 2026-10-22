/** Id prefix of every sample row added by the DEV-only demo data layer (see ./index.ts).
 *  Kept in its own dependency-free file so pages can import the guard without pulling
 *  the sample JSON into their bundle. */
export const DEMO_ID_PREFIX = 'demo-';

/** True for rows that exist only in the browser — never send their ids to the backend. */
export function isDemoId(id: unknown): boolean {
  return typeof id === 'string' && id.startsWith(DEMO_ID_PREFIX);
}

const STORAGE_KEY = 'bs_demo_data';

/** DEV-only switch of the demo data layer: `VITE_DEMO_DATA=true` or `localStorage bs_demo_data=1`. */
export function isDemoDataEnabled(): boolean {
  if (!import.meta.env.DEV) return false;
  if (import.meta.env.VITE_DEMO_DATA === 'true') return true;
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}
