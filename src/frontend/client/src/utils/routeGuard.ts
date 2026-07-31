/**
 * Route guard utility (zz customization).
 * Non-admin users visiting protected routes are redirected to the
 * customization page configured by the backend (`customization_page_url`).
 */

import type { TUser } from '~/types/chat';

export interface RouteGuardConfig {
  whitelistRoutes: string[];
  customizationPageUrl: string;
}

/**
 * Decide whether the current user should be redirected to the customization page.
 * Pass-through rules (highest priority first):
 * 1. no user — handled by the login flow, never redirect here
 * 2. role is `admin` / `group_admin`
 * 3. any of the user's role ids is listed in `administratorIds`
 * 4. current path matches the whitelist
 */
export function shouldRedirectToCustomization(
  user: TUser | null | undefined,
  pathname: string,
  config: RouteGuardConfig,
  administratorIds?: string[],
): boolean {
  if (!user) {
    return false;
  }

  if (user.role === 'admin' || user.role === 'group_admin') {
    return false;
  }

  if (administratorIds && administratorIds.length > 0) {
    try {
      const roleIds = Array.isArray(user.role)
        ? user.role
        : typeof user.role === 'string'
          ? JSON.parse(user.role)
          : [];

      if (Array.isArray(roleIds) && roleIds.some((id) => administratorIds.includes(id.toString()))) {
        return false;
      }
    } catch (e) {
      // role is not a JSON array — fall through to the whitelist check
    }
  }

  if (isInWhitelist(pathname, config.whitelistRoutes)) {
    return false;
  }

  return true;
}

function isInWhitelist(pathname: string, whitelistRoutes: string[]): boolean {
  return whitelistRoutes.some((route) => {
    // Convert parameterized routes to a regex, e.g. /chat/:id -> /chat/[^/]+
    const pattern = route
      .replace(/\//g, '\\/')
      .replace(/:\w+/g, '[^/]+')
      .replace(/\*/g, '.*');
    const regex = new RegExp(`^${pattern}$`);
    return regex.test(pathname);
  });
}
