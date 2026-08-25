import { useEffect, useRef } from 'react';
import { useRecoilState } from 'recoil';
import { useGetWorkbenchModelsQuery } from '~/hooks/queries/queries';
import store from '~/store';

interface UserLike {
  id: number | string;
}

interface ModelLike {
  id: number | string;
  name?: string;
  displayName?: string;
}

interface BsConfigLike {
  models?: ModelLike[];
}

/**
 * Hydrate / persist the chatModel atom under the user-scoped
 * `bs:{uid}:chatModel` localStorage key. Resolution order for a fresh
 * session: the user's last valid manual selection → the admin-configured
 * daily-mode default (`chat_default_model_id` from /api/v1/llm/workbench) →
 * the last configured model (compat for backends that predate the field).
 * Used by every chat surface that lets the user pick a model so the selection
 * survives page refresh and new tabs (and gets wiped on re-login alongside
 * the rest of `bs:*`).
 */
export default function useChatModelMemo(
  user: UserLike | null | undefined,
  bsConfig: BsConfigLike | undefined,
) {
  const [chatModel, setChatModel] = useRecoilState(store.chatModel);
  const hydratedRef = useRef(false);
  const { data: workbenchConfig, isLoading: workbenchLoading } = useGetWorkbenchModelsQuery();

  useEffect(() => {
    if (!bsConfig || !user?.id) return;
    if (hydratedRef.current) return;
    try {
      const savedModelId = localStorage.getItem(`bs:${user.id}:chatModel`);
      const models = bsConfig.models || [];
      let target: ModelLike | undefined | null = savedModelId
        ? models.find((m) => String(m.id) === savedModelId)
        : null;
      if (!target) {
        // No valid manual selection — the admin default decides. Wait for the
        // workbench config before settling so the default isn't skipped.
        if (workbenchLoading) return;
        const rawDefault = (workbenchConfig as Record<string, unknown> | undefined)?.chat_default_model_id;
        const adminDefaultId =
          typeof rawDefault === 'string' || typeof rawDefault === 'number' ? String(rawDefault) : null;
        if (adminDefaultId) {
          target = models.find((m) => String(m.id) === adminDefaultId) ?? null;
        }
        if (!target && models.length) target = models[models.length - 1];
      }
      if (target) {
        setChatModel({
          id: Number(target.id),
          name: target.displayName || target.name || '',
        });
      }
    } catch { /* ignore */ }
    hydratedRef.current = true;
  }, [bsConfig, user?.id, setChatModel, workbenchConfig, workbenchLoading]);

  useEffect(() => {
    if (!hydratedRef.current || !user?.id || !chatModel.id) return;
    localStorage.setItem(`bs:${user.id}:chatModel`, String(chatModel.id));
  }, [chatModel.id, user?.id]);
}
