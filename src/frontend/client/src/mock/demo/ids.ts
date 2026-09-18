/** Id prefix of every sample row added by the DEV-only demo data layer (see ./index.ts).
 *  Kept in its own dependency-free file so pages can import the guard without pulling
 *  the sample JSON into their bundle. */
export const DEMO_ID_PREFIX = 'demo-';

/** True for rows that exist only in the browser — never send their ids to the backend. */
export function isDemoId(id: unknown): boolean {
  return typeof id === 'string' && id.startsWith(DEMO_ID_PREFIX);
}
