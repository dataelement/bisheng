import { QueryClient } from '@tanstack/react-query';

export function createPlatformQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Match v3: internal APIs remain reachable even when navigator.onLine is false.
        networkMode: 'offlineFirst',
        refetchOnWindowFocus: false,
        refetchOnMount: false,
        retry: 0,
      },
      mutations: { networkMode: 'offlineFirst' },
    },
  });
}
