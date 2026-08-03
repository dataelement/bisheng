export const PORTAL_AUTH_REQUIRED_MESSAGE = 'shougang-portal:auth-required';

export interface PortalAuthWindow {
  location: Pick<Location, 'search'>;
  parent: Pick<Window, 'postMessage'>;
}

/** Notify the host portal so an embedded page never starts its own login redirect loop. */
export function notifyPortalAuthRequired(
  targetWindow: PortalAuthWindow = window,
): boolean {
  const isStandalone = targetWindow.parent === (
    targetWindow as unknown as Pick<Window, 'postMessage'>
  );
  const isPortalEmbed = new URLSearchParams(targetWindow.location.search).get('portal_embed') === '1';
  if (isStandalone || !isPortalEmbed) return false;

  try {
    targetWindow.parent.postMessage({ type: PORTAL_AUTH_REQUIRED_MESSAGE }, '*');
    return true;
  } catch {
    return false;
  }
}
