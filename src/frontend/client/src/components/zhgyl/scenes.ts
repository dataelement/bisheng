export const advisorScenes = ['procurement', 'transport', 'customs', 'orders'] as const;
export type AdvisorScene = typeof advisorScenes[number];
export type WorkspaceScene = AdvisorScene | 'select' | '';

export function advisorScene(search: string): WorkspaceScene {
  const params = new URLSearchParams(search);
  const value = params.get('agent') || params.get('scene');
  if (value === 'supply' || value === 'select') return 'select';
  return advisorScenes.find(scene => scene === value) || '';
}

export function advisorSearch(search: string): string {
  const params = new URLSearchParams(search);
  const scene = advisorScene(search);
  if (!scene) return '';
  const next = new URLSearchParams({ agent: scene === 'select' ? 'supply' : scene });
  const order = params.get('order');
  if (scene === 'orders' && order && order.length <= 100) next.set('order', order);
  return `?${next.toString()}`;
}

export function workspaceAsset(path: string): string {
  return `${import.meta.env.BASE_URL.replace(/\/$/, '')}/zhgyl/${path}`;
}

/** Only registered order-module destinations are accepted from the standalone view. */
export function orderNavigation(path: unknown, origin: string): string | null {
  if (typeof path !== 'string') return null;
  let url: URL;
  try { url = new URL(path, origin); } catch { return null; }
  const workspace = import.meta.env.BASE_URL.replace(/\/$/, '');
  if (url.origin !== origin || url.pathname !== `${workspace}/c/new`) return null;
  const params = url.searchParams;
  if (params.get('agent') !== 'orders' && params.get('module') !== 'order-tracking') return null;
  const allowed = new Set(['agent', 'module', 'order', 'view', 'mode', 'node']);
  if ([...params.keys()].some(key => !allowed.has(key))) return null;
  if (params.has('agent') && params.get('agent') !== 'orders') return null;
  if (params.has('module') && params.get('module') !== 'order-tracking') return null;
  if (params.has('view') && !['orders', 'workbench', 'reminders'].includes(params.get('view') || '')) return null;
  if (params.has('node') && !['payment', 'delivery', 'settlement'].includes(params.get('node') || '')) return null;
  if (params.has('mode') && !['default', '7', '30', 'off'].includes(params.get('mode') || '')) return null;
  if ((params.get('order') || '').length > 100) return null;
  return `/c/new${url.search}`;
}
