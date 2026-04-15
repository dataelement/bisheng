/**
 * Last visited path per main-nav section — updated synchronously in MainLayout render
 * so NavLink targets and this module's mobile tab bar stay consistent.
 */
export const lastSectionPaths: Record<string, string> = {};

export function appsSectionLinkTarget(): string {
  const p = lastSectionPaths.apps;
  if (!p) return '/apps';
  return p.startsWith('/apps/explore') ? '/apps' : p;
}
