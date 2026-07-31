import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import { shouldRedirectToCustomization } from '~/utils/routeGuard';
import { useAuthContext } from './AuthContext';

/**
 * zz customization route guard: redirect non-admin users to the customization
 * page configured by the backend (`customization_page_url` in /api/v1/env).
 * No-op until the env config has loaded (bishengConfState defaults to null)
 * or when the URL is not configured.
 */
export const useRouteGuard = () => {
  const { user } = useAuthContext();
  const location = useLocation();
  const bsConfig = useRecoilValue(bishengConfState);

  useEffect(() => {
    const customizationPageUrl = bsConfig?.customization_page_url;
    if (user && customizationPageUrl) {
      const guardConfig = {
        whitelistRoutes: ['/login', '/reset', '/403'],
        customizationPageUrl,
      };

      if (
        shouldRedirectToCustomization(user, location.pathname, guardConfig, bsConfig?.administrator_ids)
      ) {
        window.location.href = customizationPageUrl;
      }
    }
  }, [user, location.pathname, bsConfig]);
};
