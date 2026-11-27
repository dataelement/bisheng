import { advisorScene } from '~/components/zhgyl/scenes';

export type SidebarChatEntry = 'home' | 'zhgyl-forecast' | 'zhgyl-orders';

/** Query-selected modules share /c/new, so pathname matching alone cannot select a row. */
export function sidebarChatEntry(pathname: string, search: string): SidebarChatEntry | null {
  if (!/^\/(c|linsight)(\/|$)/.test(pathname)) return null;
  const params = new URLSearchParams(search);
  if (/^\/c\/new\/?$/.test(pathname)) {
    const module = params.get('module');
    if (module === 'procurement-forecast') return 'zhgyl-forecast';
    if (module === 'order-tracking') return 'zhgyl-orders';
    if (module) return null;
  }
  if (/^\/c\/[^/]+\/?$/.test(pathname) && advisorScene(search) === 'orders') return 'zhgyl-orders';
  return 'home';
}
