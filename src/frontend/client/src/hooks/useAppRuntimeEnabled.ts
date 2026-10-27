import { useQuery } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import type { BishengConfig } from '~/@types/chat';
import { getBysConfigApi } from '~/api/apps';

/**
 * Shared cache key for `GET /api/v1/env`.
 *
 * Exported so that any future consumer reuses the same react-query entry
 * instead of firing its own request for the same payload.
 */
export const BISHENG_ENV_QUERY_KEY = ['bishengEnvConfig'] as const;

/**
 * `GET /api/v1/env` as a react-query v4 query.
 *
 * Why not Recoil: `bishengConfState` already holds this payload, but Recoil is
 * frozen in this app (`no-restricted-imports`, ledger #5) and new files may not
 * import it — see `useVersionManagementEnabled` for the pre-freeze shape. The
 * query is configured to never go stale, so every consumer shares one fetch per
 * session no matter how many components mount.
 */
export function useBishengEnvQuery(): UseQueryResult<BishengConfig | null> {
  return useQuery({
    queryKey: BISHENG_ENV_QUERY_KEY,
    queryFn: async () => {
      // `request.get` resolves to the `{status_code, status_message, data}`
      // envelope; the env payload sits one level down.
      const envelope = (await getBysConfigApi()) as { data?: BishengConfig } | null;
      return envelope?.data ?? null;
    },
    // Deploy-time flags: they cannot change while the tab is open.
    staleTime: Infinity,
    cacheTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

/**
 * F054 AC-62 — whether the app-factory runtime layer is deployed.
 *
 * Fails closed: while the config is still loading, when the request fails, and
 * on backends that predate the flag, this returns `false`, so app-factory-only
 * UI stays hidden rather than flashing in and then disappearing. Callers that
 * need to tell "loading" from "not deployed" apart can read
 * `useBishengEnvQuery().isLoading` directly.
 */
export function useAppRuntimeEnabled(): boolean {
  const { data } = useBishengEnvQuery();
  return data?.app_runtime_enabled === true;
}
