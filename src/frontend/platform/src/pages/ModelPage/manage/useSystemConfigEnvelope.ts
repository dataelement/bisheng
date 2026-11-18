import type { SystemModelConfigEnvelope } from "@/controllers/API/finetune";
import { showApiError } from "@/controllers/request";
import { useCallback, useEffect, useRef, useState } from "react";

interface ReloadOptions {
    // Partial prompt saves refresh provenance while preserving other field drafts.
    updateConfig?: boolean;
}

interface UseEnvelopeResult<T> {
    config: T | null;
    loading: boolean;
    error: unknown;
    inheritedFromRoot: boolean;
    fallbackBlocked: boolean;
    reload: (options?: ReloadOptions) => Promise<SystemModelConfigEnvelope<T> | null>;
}

/** Reload only this column's saved value; draft edits never change its source. */
export function useSystemConfigEnvelope<T = unknown>(
    fetcher: () => Promise<SystemModelConfigEnvelope<T>>,
): UseEnvelopeResult<T> {
    const [error, setError] = useState<unknown>(null);
    const [config, setConfig] = useState<T | null>(null);
    const [loading, setLoading] = useState(true);
    const [inheritedFromRoot, setInheritedFromRoot] = useState(false);
    const [fallbackBlocked, setFallbackBlocked] = useState(false);
    const fetcherRef = useRef(fetcher);
    const mountedRef = useRef(true);
    const generationRef = useRef(0);
    fetcherRef.current = fetcher;

    const reload = useCallback(async ({ updateConfig = true }: ReloadOptions = {}) => {
        if (!mountedRef.current) return null;
        const generation = ++generationRef.current;
        try {
            const env = await fetcherRef.current();
            if (!mountedRef.current || generation !== generationRef.current) return null;
            if (updateConfig) setConfig(env?.data ?? null);
            setInheritedFromRoot(!!env?.inherited_from_root);
            setFallbackBlocked(!!env?.fallback_blocked);
            setError(null);
            return env;
        } catch (cause: unknown) {
            if (!mountedRef.current || generation !== generationRef.current) return null;
            setError(cause);
            throw cause;
        } finally {
            if (mountedRef.current && generation === generationRef.current) setLoading(false);
        }
    }, []);

    useEffect(() => {
        mountedRef.current = true;
        void reload().catch(showApiError);
        return () => {
            mountedRef.current = false;
            generationRef.current += 1;
        };
    }, [reload]);

    return { config, loading, error, inheritedFromRoot, fallbackBlocked, reload };
}
