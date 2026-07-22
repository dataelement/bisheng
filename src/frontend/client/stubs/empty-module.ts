// Empty stub for node-only dynamic imports reached from browser-safe code paths
// (e.g. @dicebear/core `toFile()` → import('node:fs/promises'), never called in
// the browser). vite-plugin-node-polyfills maps bare `fs` but mangles the
// `fs/promises` subpath under the pnpm workspace layout, so we alias the
// subpath here explicitly.
export default {};
