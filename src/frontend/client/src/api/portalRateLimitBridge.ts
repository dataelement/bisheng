export const PORTAL_RATE_LIMIT_MESSAGE = 'shougang-portal:rate-limit';
export const API_RATE_LIMIT_CODE = 10042;
const DEFAULT_RATE_LIMIT_MESSAGE = '请求过于频繁，请稍后重试';

export interface PortalRateLimitNotice {
  code: number;
  message: string;
}

export interface PortalRateLimitWindow {
  location: Pick<Location, 'search'>;
  parent: Pick<Window, 'postMessage'>;
}

/** 将嵌入式 Client 的限流提示交给门户父页面统一展示。 */
export function notifyPortalRateLimit(
  notice: PortalRateLimitNotice,
  targetWindow: PortalRateLimitWindow = window,
): boolean {
  const isStandalone = targetWindow.parent === (
    targetWindow as unknown as Pick<Window, 'postMessage'>
  );
  const isPortalEmbed = new URLSearchParams(targetWindow.location.search).get('portal_embed') === '1';
  if (isStandalone || !isPortalEmbed) return false;

  const code = Number.isInteger(notice.code) && notice.code >= 10000 && notice.code <= 99999
    ? notice.code
    : API_RATE_LIMIT_CODE;
  const message = notice.message.trim().slice(0, 500) || DEFAULT_RATE_LIMIT_MESSAGE;

  try {
    targetWindow.parent.postMessage({
      type: PORTAL_RATE_LIMIT_MESSAGE,
      code,
      message,
    }, '*');
    return true;
  } catch {
    return false;
  }
}
