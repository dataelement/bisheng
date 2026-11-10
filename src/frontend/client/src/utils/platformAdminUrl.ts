/**
 * 本地开发：工作台在 :4001、管理端在 :3001，相对路径 /admin 会错误地指向 4001。
 * 生产：通常同源反代，用当前 origin + BISHENG_HOST 即可。
 *
 * 开发态的跨端基址解析顺序：
 *   1. `__APP_ENV__.PLATFORM_ORIGIN`（vite 读 `VITE_PLATFORM_ORIGIN` 注入）；
 *   2. 未配置时，用**浏览器当前主机名** + 平台端口推导——这样 localhost、
 *      127.0.0.1、局域网 IP 访问都能跳到同主机的管理端，而不是写死 localhost；
 *   3. 非开发态回落到当前 origin（同源反代形态）。
 */

/** 平台开发服务器端口（strictPort，见 platform/vite.config.mts）。 */
const DEV_PLATFORM_PORT = '3001';

type PlatformEnvLike = {
  BISHENG_HOST?: string;
  PLATFORM_ORIGIN?: string;
};

type LocationLike = {
  origin?: string;
  protocol?: string;
  hostname?: string;
};

export function resolvePlatformOrigin(
  appEnv: PlatformEnvLike,
  loc?: LocationLike | null,
  isDev = false,
): string {
  const configured = appEnv.PLATFORM_ORIGIN?.trim().replace(/\/$/, '') || '';
  if (configured) return configured;

  // Two dev servers, two ports, same host as the browser used.
  if (isDev && loc?.hostname) {
    return `${loc.protocol || 'http:'}//${loc.hostname}:${DEV_PLATFORM_PORT}`;
  }

  return (loc?.origin || '').replace(/\/$/, '');
}

export function getPlatformAdminPanelUrl(
  search?: string,
  // Test seam: callers never pass this; it defaults to the bundler's dev flag.
  isDev = Boolean(import.meta.env?.DEV),
): string {
  const path = __APP_ENV__.BISHENG_HOST || '/admin';
  const origin = resolvePlatformOrigin(
    __APP_ENV__,
    typeof location !== 'undefined' ? location : null,
    isDev,
  );
  const suffix = path.startsWith('/') ? path : `/${path}`;
  let url = `${origin}${suffix}`;
  if (search) {
    url += search.startsWith('?') ? search : `?${search}`;
  }
  return url;
}
