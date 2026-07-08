import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { EffectiveQuotaItem, getEffectiveQuotaApi } from "~/api/quota";

export type QuotaResource =
    | "channel"
    | "knowledge_space"
    | "knowledge_space_subscribe"
    | "knowledge_space_file";

/**
 * Shared query key so every consumer reads one cached fetch and a post-upload
 * `queryClient.invalidateQueries(EFFECTIVE_QUOTA_QUERY_KEY)` refreshes them all.
 */
export const EFFECTIVE_QUOTA_QUERY_KEY = ["quota", "effective"] as const;

/**
 * Reads the current user's effective quota (role + tenant) from
 * /api/v1/quota/effective so callers stop hard-coding limits. `effective === -1`
 * means unlimited. The backend stays the authoritative enforcer; this hook only
 * powers upfront UX checks, so an unknown / not-yet-loaded quota never blocks.
 *
 * Backed by react-query: all consumers share one cached request, and the default
 * refetch-on-window-focus keeps the storage bar fresh after uploads.
 */
export function useEffectiveQuota() {
    const {
        data: items = [],
        isLoading,
        refetch,
    } = useQuery({
        queryKey: EFFECTIVE_QUOTA_QUERY_KEY,
        queryFn: getEffectiveQuotaApi,
        // A stale-but-usable quota is fine for upfront UX; avoid refetch storms.
        staleTime: 30_000,
    });

    const quotas = useMemo(() => {
        const map: Record<string, EffectiveQuotaItem> = {};
        items.forEach((item) => {
            map[item.resource_type] = item;
        });
        return map;
    }, [items]);

    // Preserve the previous `refresh()` contract: fire a refetch, resolve to void.
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
