/**
 * Docs-site stub for `filenamify` (rspress.config resolve.alias).
 *
 * The real package imports `node:path`, which rspack cannot bundle for the
 * browser ("unhandled scheme" — resolve.fallback doesn't cover node:-prefixed
 * ids). It only reaches the docs bundle through the ~/hooks barrel
 * (Conversations/usePresets), a path no demo executes, so an identity shim is
 * enough to keep the bundle compiling.
 */
export default function filenamify(input: string): string {
  return input;
}
