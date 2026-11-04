import type { UseChatModelSelectionOptions } from "./chatSurfaceTypes";
import { useCallback } from "react";
import {
  useChatModelResolution,
  type ChatModelOption,
} from "~/hooks/useChatModelResolution";

export function useChatModelSelection({
  conversationId,
  bsConfig,
  user,
  setChatModel,
  modelMode,
  adminDefaultModelId,
  taskConversationModelId,
}: UseChatModelSelectionOptions) {
  const handleModelResolved = useCallback(
    (target: ChatModelOption, deliberate: boolean) => {
      setChatModel({
        id: Number(target.id),
        name: target.displayName || target.name || "",
        manual: deliberate,
        mode: modelMode,
      });
    },
    [setChatModel, modelMode],
  );

  const { persistPick: persistModelPick } = useChatModelResolution({
    userId: user?.id,
    conversationId,
    mode: modelMode,
    models: (bsConfig?.models || []) as ChatModelOption[],
    adminDefaultId: adminDefaultModelId,
    serverModelId: taskConversationModelId,
    ready: !!bsConfig?.models?.length && !!user?.id,
    onResolved: handleModelResolved,
  });

  // The picker writes both the conversation record and the user-level default,
  // so this conversation keeps the choice and the next new one inherits it.
  const handleModelChange = useCallback(
    (val: string | number) => {
      const model = bsConfig?.models?.find(
        (m: ChatModelOption) => String(m.id) === String(val),
      );
      persistModelPick(val);
      setChatModel({
        id: Number(val),
        name: model?.displayName || "",
        manual: true,
        mode: modelMode,
      });
    },
    [bsConfig, persistModelPick, setChatModel, modelMode],
  );

  // AiModelSelect repairing an invalid value is NOT a user pick — never persist it.
  const handleModelAutoChange = useCallback(
    (val: string | number) => {
      const model = bsConfig?.models?.find(
        (m: ChatModelOption) => String(m.id) === String(val),
      );
      setChatModel((prev) => ({
        id: Number(val),
        name: model?.displayName || prev.name || "",
        manual: prev.manual ?? false,
        mode: prev.mode,
      }));
    },
    [bsConfig, setChatModel],
  );

  return { handleModelChange, handleModelAutoChange };
}
