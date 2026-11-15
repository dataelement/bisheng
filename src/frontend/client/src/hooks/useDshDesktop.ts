import { useQuery } from '@tanstack/react-query';
import { getDshBrowserConfig } from '~/api/dsh';
import { DEFAULT_DSH_LAUNCH_URL } from '~/utils/dshLaunch';

export function useDshDesktop() {
  const query = useQuery({
    queryKey: ['dsh-browser-config'], queryFn: ({ signal }) => getDshBrowserConfig(signal),
    retry: false, refetchInterval: 30000, refetchOnWindowFocus: 'always', staleTime: 0,
  });
  const enabled = !query.isError && query.data?.enabled === true && query.data.management_enabled;
  return { enabled, downloadUrl: query.data?.download_url ?? null, launchUrl: query.data?.launch_url ?? DEFAULT_DSH_LAUNCH_URL };
}
