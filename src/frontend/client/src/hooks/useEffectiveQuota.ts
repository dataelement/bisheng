import { useCallback, useEffect, useState } from "react";
import { EffectiveQuotaItem, getEffectiveQuotaApi } from "~/api/quota";

export type QuotaResource =
    | "channel"
    | "knowledge_space"
    | "knowledge_space_subscribe"
    | "knowledge_space_file";

/**
 * Reads the current user's effective quota (role + tenant) from
 * /api/v1/quota/effective so callers stop hard-coding limits. `effective === -1`
 * means unlimited. The backend stays the authoritative enforcer; this hook only
 * powers upfront UX checks, so an unknown / not-yet-loaded quota never blocks.
 */
export function useEffectiveQuota() {
    const [quotas, setQuotas] = useState<Record<string, EffectiveQuotaItem>>({});
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        try {
            const items = await getEffectiveQuotaApi();
            const map: Record<string, EffectiveQuotaItem> = {};
            items.forEach((item) => {
                map[item.resource_type] = item;
            });
            setQuotas(map);
        } catch (error) {
            console.error("Failed to fetch effective quota:", error);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void refresh();
    }, [refresh]);

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

    return { quotas, loading, refresh, getEffective, isOverQuota };
}
