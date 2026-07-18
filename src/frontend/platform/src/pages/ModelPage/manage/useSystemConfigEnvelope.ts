// F022: shared hook for the 4 simple system-config tabs
// (Knowledge / Assistant / Evaluation / Workflow). Each tab fetches an
// envelope-shaped GET response with `data` + `inherited_from_root` +
// `fallback_blocked`; the hook tracks loading state, exposes the typed
// config + flags, and gives the caller a `clearInherited()` helper to
// flip the badge off the first time the user edits a field.
//
// Workbench is intentionally NOT migrated: it uses react-query (with
// shared cache invalidation across the rest of the page) and a
// different config shape, so its inline destructure stays.

import { useEffect, useState } from "react";
import type { SystemModelConfigEnvelope } from "@/controllers/API/finetune";

interface UseEnvelopeResult<T> {
    config: T | null;
    loading: boolean;
    inheritedFromRoot: boolean;
    fallbackBlocked: boolean;
    clearInherited: () => void;
}

export function useSystemConfigEnvelope<T = any>(
    fetcher: () => Promise<SystemModelConfigEnvelope<T>>,
): UseEnvelopeResult<T> {
    const [config, setConfig] = useState<T | null>(null);
    const [loading, setLoading] = useState<boolean>(true);
    const [inheritedFromRoot, setInheritedFromRoot] = useState<boolean>(false);
    const [fallbackBlocked, setFallbackBlocked] = useState<boolean>(false);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        fetcher()
            .then((env) => {
                if (cancelled) return;
                setConfig((env?.data ?? null) as T | null);
                setInheritedFromRoot(!!env?.inherited_from_root);
                setFallbackBlocked(!!env?.fallback_blocked);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => { cancelled = true; };
        // fetcher is treated as stable per the documented call sites
        // (all 4 are module-level imports). Re-binding the effect on
        // every render would refetch on parent re-renders for free.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const clearInherited = () => {
        setInheritedFromRoot((prev) => prev ? false : prev);
    };

    return { config, loading, inheritedFromRoot, fallbackBlocked, clearInherited };
}
