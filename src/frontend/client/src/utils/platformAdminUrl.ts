/**
 * 本地开发：工作台在 :4001、管理端在 :3001，相对路径 /admin 会错误地指向 4001。
 * 生产：通常同源反代，用当前 origin + BISHENG_HOST 即可。
 */
export function getPlatformAdminPanelUrl(search?: string): string {
  const path = __APP_ENV__.BISHENG_HOST || '/admin';
  const platformOrigin = (__APP_ENV__ as { PLATFORM_ORIGIN?: string }).PLATFORM_ORIGIN?.replace(/\/$/, '') || '';
  const origin = platformOrigin || (typeof location !== 'undefined' ? location.origin : '');
  const suffix = path.startsWith('/') ? path : `/${path}`;
  let url = `${origin}${suffix}`;
  if (search) {
    url += search.startsWith('?') ? search : `?${search}`;
  }
  return url;
}
