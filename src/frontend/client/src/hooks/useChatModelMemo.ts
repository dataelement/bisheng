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
 * Hydrate / persist the chatModel atom. Two per-user localStorage records
 * keep the modes' memories separate: `bs:{uid}:chatModel` for daily mode and
 * `bs:{uid}:taskModel` for task mode. Both store ONLY explicit user picks;
 * resolution order for a fresh daily session: the user's last valid manual
 * selection → the admin-configured daily-mode default
 * (`chat_default_model_id` from /api/v1/llm/workbench) → the last configured
 * model (compat for backends that predate the field). Auto-applied defaults
 * carry `manual: false` and are never persisted, so they keep following the
 * admin config instead of freezing into a fake "manual" record. Used by every
 * chat surface that lets the user pick a model so the selection survives
 * page refresh and new tabs (and gets wiped on re-login alongside the rest
 * of `bs:*`).
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
      const key = `bs:${user.id}:chatModel`;
      const savedModelId = localStorage.getItem(key);
      const models = bsConfig.models || [];
      let manual = false;
      let target: ModelLike | undefined | null = savedModelId
        ? models.find((m) => String(m.id) === savedModelId)
        : null;
      if (target) {
        manual = true;
      } else {
        // A saved id that no longer resolves (model removed/disabled) is a
        // stale record — drop it so the admin default takes over for good.
        if (savedModelId) localStorage.removeItem(key);
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
          manual,
          mode: 'daily',
        });
      }
    } catch { /* ignore */ }
    hydratedRef.current = true;
  }, [bsConfig, user?.id, setChatModel, workbenchConfig, workbenchLoading]);

  useEffect(() => {
    if (!hydratedRef.current || !user?.id || !chatModel.id) return;
    // Only explicit user picks become a remembered selection, and each mode
    // writes its own record.
    if (!chatModel.manual) return;
    const key = chatModel.mode === 'task' ? `bs:${user.id}:taskModel` : `bs:${user.id}:chatModel`;
    localStorage.setItem(key, String(chatModel.id));
  }, [chatModel.id, chatModel.manual, chatModel.mode, user?.id]);
}
