import { getPlatformAdminPanelUrl } from './platformAdminUrl';

/**
 * Single implementation of "send this browser to the login page, and bring it
 * back here afterwards".
 *
 * Used by the 401 response interceptor (`~/api/request.ts`) and by the
 * `RequireLogin` route guard. Keeping both on this function is deliberate: two
 * hand-rolled copies drifted before (the interceptor stored only
 * `location.pathname`, losing query and hash).
 *
 * CROSS-APP CONTRACT — the two localStorage keys below are read by the
 * *platform* app after a successful login:
 *   - `src/frontend/platform/src/utils/loginReturnTo.ts` (validate + consume)
 *   - consumed from the local login form and from the authenticated landing
 *     (SSO callbacks never touch the local form).
 * Rename them in both apps or not at all.
 */
export const LOGIN_PATHNAME_KEY = 'LOGIN_PATHNAME';
export const LOGIN_PATHNAME_AT_KEY = 'LOGIN_PATHNAME_AT';

/** Auth-state sentinel dropped on the way out, mirroring the 401 interceptor. */
const AUTH_STATE_KEY = 'bs:auth-state';

/** Set once we hand the document over, so concurrent 401s can't double-navigate. */
let redirecting = false;

/**
 * The full location to come back to: pathname + query + hash.
 *
 * The share route encodes everything in the path (`/share/:token/:vid?`), but
 * other callers (article links, `?error=` deep links) carry state in the query,
 * and dropping it silently lands the user on a different page than they asked
 * for.
 */
export function buildReturnTo(): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

/**
 * Persist where to come back to. Stored as an ABSOLUTE, same-origin URL: the
 * platform app performs the return navigation, so a bare path would resolve
 * against the *platform* origin — wrong whenever the two apps are not
 * co-served (local dev is :4001 vs :3001).
 */
function rememberReturnTo(returnTo: string): void {
  try {
    const absolute = new URL(returnTo, location.origin);
    if (absolute.origin !== location.origin) {
      // Never persist a foreign origin — that would turn the post-login
      // navigation into an open redirect.
      return;
    }
    localStorage.setItem(LOGIN_PATHNAME_KEY, absolute.href);
    localStorage.setItem(LOGIN_PATHNAME_AT_KEY, String(Date.now()));
  } catch {
    /* storage disabled / quota — losing the return path is not fatal */
  }
}

/** Where the login form lives: the IdP when SSO is configured, else the platform app. */
export function getLoginUrl(): string {
  try {
    const thirdPartyLoginUrl = localStorage.getItem('THIRD_PARTY_LOGIN_URL');
    if (thirdPartyLoginUrl) {
      return thirdPartyLoginUrl;
    }
  } catch {
    /* ignore storage errors and fall through to the platform login */
  }
  return getPlatformAdminPanelUrl();
}

/**
 * Hand the document over to the login page, remembering `returnTo` so the user
 * lands back here once authenticated.
 *
 * Idempotent: the first call wins. A page that fires several requests in
 * parallel produces several 401s, and each one used to assign
 * `location.href` again.
 *
 * `force` bypasses that guard. The guard exists to dedupe concurrent 401s, not
 * to veto user intent — a "log in" button must still work after an automatic
 * attempt has already been made, otherwise it is dead exactly when the
 * automatic path failed and the user needs it.
 */
export function redirectToLogin(
  returnTo: string = buildReturnTo(),
  { force = false }: { force?: boolean } = {},
): void {
  if (redirecting && !force) {
    return;
  }
  redirecting = true;

  // Drop the auth-state sentinel so the next successful /user/info is treated
  // as a fresh session and re-applies admin-configured chat defaults.
  try {
    localStorage.removeItem(AUTH_STATE_KEY);
  } catch {
    /* ignore storage errors */
  }

  rememberReturnTo(returnTo);
  location.href = getLoginUrl();
}

/** Test-only: reset the one-shot guard between cases. */
export function __resetRedirectGuardForTests(): void {
  redirecting = false;
}
