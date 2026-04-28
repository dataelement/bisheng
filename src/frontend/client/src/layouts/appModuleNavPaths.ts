/**
 * Last visited path per main-nav section — updated synchronously in MainLayout render
 * so NavLink targets and this module's mobile tab bar stay consistent.
 */
export const lastSectionPaths: Record<string, string> = {};

export function appsSectionLinkTarget(): string {
  const p = lastSectionPaths.apps;
  if (!p) return '/apps';
  // App center tab should always land on the center home when current path is
  // inside app chat (/app/*) or explore sub-page (/apps/explore).
  if (p.startsWith('/apps/explore') || p.startsWith('/app/')) return '/apps';
  return p;
}
