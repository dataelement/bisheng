import { useEffect, useRef } from "react";
import { useClientEnvironment } from "~/hooks/useClientEnvironment";
import {
  postMobileHost,
  publishMobileHost,
  runMobileHostSend,
  type MobileHostApi,
  type PreparedMobileHostSend,
} from "~/utils/mobileHostBridge";

type MobileHostBridgeInput = {
  userLoaded: boolean;
  isLoading: boolean;
  conversationId?: string;
  messageCount: number;
  navigate: (path: string, opts: { replace: boolean }) => void;
  sendMessage: (
    text: string,
    files: Array<Record<string, unknown>>,
    opts: {
      taskMode: boolean;
      hostDraft: PreparedMobileHostSend;
      onTurnCreated: (conversationId: string) => void;
    },
  ) => Promise<boolean>;
  apply: (prepared: PreparedMobileHostSend) => void;
};

/** Lets the phone send on this already-open page. A normal browser gets nothing. */
export function useMobileHostBridge(input: MobileHostBridgeInput): void {
  const { capabilities } = useClientEnvironment();
  const enabled = capabilities.hasHostChatHeader && input.userLoaded;
  const inputRef = useRef(input);
  inputRef.current = input;

  useEffect(() => {
    if (!enabled) return undefined;
    const api: MobileHostApi = {
      send: (draft) => runMobileHostSend(draft, {
        conversationId: inputRef.current.conversationId,
        apply: (prepared) => inputRef.current.apply(prepared),
        sendMessage: (text, files, opts) => inputRef.current.sendMessage(text, files, opts),
        post: postMobileHost,
      }),
      resetBlank: () => inputRef.current.navigate("/c/new", { replace: true }),
    };
    publishMobileHost(true, api);
    return () => publishMobileHost(false, api);
  }, [enabled]);

  useEffect(() => {
    if (!enabled || input.isLoading) return;
    postMobileHost({ type: "shell-ready" });
  }, [enabled, input.isLoading]);

  useEffect(() => {
    if (!enabled || input.isLoading) return;
    if (input.conversationId !== "new") return;
    if (input.messageCount > 0) return;
    postMobileHost({ type: "blank-ready" });
  }, [enabled, input.isLoading, input.conversationId, input.messageCount]);
}
