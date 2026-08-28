import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { EffectiveQuotaItem, getEffectiveQuotaApi } from "~/api/quota";

export type QuotaResource =
  | "channel"
  | "info_source_subscribe"
  | "knowledge_space"
  | "knowledge_space_subscribe"
  | "knowledge_space_file";

/**
 * Shared cache key: the personal storage card and the upload guards must read
 * the same server result, so every consumer goes through this one query.
 */
export const EFFECTIVE_QUOTA_QUERY_KEY = ["effective-quota"] as const;

/** Invalidate the shared quota cache after anything that changes usage or limits. */
export function useRefreshEffectiveQuota() {
    const queryClient = useQueryClient();
    return useCallback(
        () => queryClient.invalidateQueries({ queryKey: EFFECTIVE_QUOTA_QUERY_KEY }),
        [queryClient],
    );
}

/**
 * Reads the current user's effective quota (role + tenant) from
 * /api/v1/quota/effective so callers stop hard-coding limits. `effective === -1`
 * means unlimited. The backend stays the authoritative enforcer; this hook only
 * powers upfront UX checks, so an unknown / not-yet-loaded quota never blocks.
 */
export function useEffectiveQuota() {
    const { data, isLoading, refetch } = useQuery({
        queryKey: EFFECTIVE_QUOTA_QUERY_KEY,
        queryFn: getEffectiveQuotaApi,
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });

    const quotas = useMemo(() => {
        const map: Record<string, EffectiveQuotaItem> = {};
        (data ?? []).forEach((item) => {
            map[item.resource_type] = item;
        });
        return map;
    }, [data]);

    const refresh = useCallback(async () => {
        await refetch();
    }, [refetch]);

  // -1 (unlimited) when the quota is unknown, so an unloaded quota never blocks.
  const getEffective = useCallback(
    (type: QuotaResource): number => quotas[type]?.effective ?? -1,
    [quotas],
  );

  // True only when the quota is known, finite, and already reached.
  const isOverQuota = useCallback(
    (type: QuotaResource, currentUsed: number): boolean => {
      const effective = quotas[type]?.effective;
      return effective != null && effective !== -1 && currentUsed >= effective;
    },
    [quotas],
  );

    return { quotas, loading: isLoading, refresh, getEffective, isOverQuota };
}
