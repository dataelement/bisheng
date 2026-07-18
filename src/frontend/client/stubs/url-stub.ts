/**
 * Browser stub for Node's `url` module (docs site / rspress build only).
 *
 * `src/api/chat/actions.ts` (reached transitively through the `~/utils` barrel)
 * does `import { URL } from 'url'`. In the browser the global URL is identical,
 * so re-export it to satisfy strict ESM linking. Never executed beyond that.
 */
export const URL = globalThis.URL;
export default { URL };
