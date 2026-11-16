import { useQuery } from '@tanstack/react-query';
import { DSH_BROWSER_CONFIG_CACHE_OPTIONS, DSH_BROWSER_CONFIG_QUERY_KEY } from '@bisheng/api-client';
import { getDshBrowserConfig } from '~/api/dsh';
import { DEFAULT_DSH_LAUNCH_URL } from '~/utils/dshLaunch';

export function useDshDesktop() {
  const query = useQuery({
    queryKey: DSH_BROWSER_CONFIG_QUERY_KEY, queryFn: ({ signal }) => getDshBrowserConfig(signal),
    ...DSH_BROWSER_CONFIG_CACHE_OPTIONS,
  });
  const enabled = !query.isError && query.data?.enabled === true && query.data.management_enabled;
  return { enabled, downloadUrl: query.data?.download_url ?? null, launchUrl: query.data?.launch_url ?? DEFAULT_DSH_LAUNCH_URL };
}
