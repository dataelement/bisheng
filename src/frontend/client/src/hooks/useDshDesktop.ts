import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { getDshBrowserConfig } from '~/api/dsh';

export function useDshDesktop() {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ['dsh-browser-config'], queryFn: ({ signal }) => getDshBrowserConfig(signal),
    retry: false, refetchInterval: 30000, refetchOnWindowFocus: 'always', staleTime: 0,
  });
  const enabled = !query.isError && query.data?.enabled === true && query.data.management_enabled;
  useEffect(() => { if (!enabled) setOpen(false); }, [enabled]);
  return { open: open && enabled, setOpen, enabled, downloadUrl: query.data?.download_url ?? null };
}
