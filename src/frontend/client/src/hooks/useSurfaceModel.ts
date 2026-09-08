/**
 * Model selection for the satellite chat surfaces — the knowledge-space Q&A
 * input, the article dock, the file dock and the subscription AI panel.
 *
 * These used to read and write the same global `chatModel` atom as /c, so
 * picking a model inside the knowledge space immediately changed what the main
 * chat showed. Each surface now keeps its own selection in local state, backed
 * by `bs:{uid}:surfaceModel:{surfaceKey}`, and never touches the atom.
 *
 * Resolution reuses the shared chain (user record → admin default → last
 * configured model); the per-conversation layer does not apply here because a
 * surface is a single long-lived panel rather than a list of conversations.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { resolveChatModel, type ChatModelOption } from '~/hooks/useChatModelResolution';

export interface SurfaceModelValue {
    id: number;
    name: string;
}

export interface UseSurfaceModelParams {
    userId?: string | number | null;
    /** Stable, surface-identifying slug, e.g. `knowledgeAi`. */
    surfaceKey: string;
    models: ChatModelOption[];
    adminDefaultId?: string | null;
}

export interface UseSurfaceModelResult {
    model: SurfaceModelValue;
    /** A user's explicit pick — remembered for this surface. */
    selectModel: (modelId: string | number) => void;
    /**
     * AiModelSelect repairing an out-of-range value. Never persisted: writing it
     * would freeze the admin default into a fake "user pick" that then outranks
     * later admin changes.
     */
    repairModel: (modelId: string | number) => void;
}

const storageKey = (userId: string, surfaceKey: string) =>
    `bs:${userId}:surfaceModel:${surfaceKey}`;

const EMPTY_MODEL: SurfaceModelValue = { id: 0, name: '' };

const toValue = (option: ChatModelOption): SurfaceModelValue => ({
    id: Number(option.id),
    name: option.displayName || option.name || '',
});

export function useSurfaceModel({
    userId,
    surfaceKey,
    models,
    adminDefaultId,
}: UseSurfaceModelParams): UseSurfaceModelResult {
    const [model, setModel] = useState<SurfaceModelValue>(EMPTY_MODEL);
    const resolvedRef = useRef(false);
    const uid = userId === null || userId === undefined ? '' : String(userId);
    const key = uid ? storageKey(uid, surfaceKey) : '';

    useEffect(() => {
        if (resolvedRef.current || !key || !models.length) return;
        let saved: string | null = null;
        try {
            saved = localStorage.getItem(key);
        } catch { /* private mode — fall through to the defaults */ }

        const { target, staleSources } = resolveChatModel({
            models,
            mode: 'daily',
            userSavedId: saved,
            adminDefaultId,
        });
        if (staleSources.includes('user')) {
            try {
                localStorage.removeItem(key);
            } catch { /* ignore */ }
        }
        if (!target) return;
        resolvedRef.current = true;
        setModel(toValue(target));
    }, [key, models, adminDefaultId]);

    const selectModel = useCallback(
        (modelId: string | number) => {
            const picked = models.find((m) => String(m.id) === String(modelId));
            if (!picked) return;
            resolvedRef.current = true;
            setModel(toValue(picked));
            if (!key) return;
            try {
                localStorage.setItem(key, String(modelId));
            } catch { /* ignore */ }
        },
        [models, key],
    );

    const repairModel = useCallback(
        (modelId: string | number) => {
            const picked = models.find((m) => String(m.id) === String(modelId));
            if (!picked) return;
            resolvedRef.current = true;
            setModel(toValue(picked));
        },
        [models],
    );

    return useMemo(
        () => ({ model, selectModel, repairModel }),
        [model, selectModel, repairModel],
    );
}
