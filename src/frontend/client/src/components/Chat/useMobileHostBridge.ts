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
  configReady: boolean;
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
  const ready = enabled && input.configReady && !input.isLoading;
  const inputRef = useRef(input);
  const sendPendingRef = useRef(false);
  inputRef.current = input;

  useEffect(() => {
    if (!enabled) return undefined;
    const api: MobileHostApi = {
      send: async (draft) => {
        // Lock before the lease or request can yield. React's streaming state
        // does not update soon enough to protect two host calls in one tick.
        if (sendPendingRef.current) return;
        if (!inputRef.current.configReady || inputRef.current.isLoading) {
          postMobileHost({ type: "send-failed", handedOff: false });
          return;
        }
        sendPendingRef.current = true;
        try {
          await runMobileHostSend(draft, {
            conversationId: inputRef.current.conversationId,
            apply: (prepared) => inputRef.current.apply(prepared),
            sendMessage: (text, files, opts) => inputRef.current.sendMessage(text, files, opts),
            post: postMobileHost,
          });
        } finally {
          sendPendingRef.current = false;
        }
      },
      resetBlank: () => inputRef.current.navigate("/c/new", { replace: true }),
    };
    publishMobileHost(true, api);
    return () => publishMobileHost(false, api);
  }, [enabled]);

  useEffect(() => {
    if (!ready) return;
    postMobileHost({ type: "shell-ready" });
  }, [ready]);

  useEffect(() => {
    if (!ready) return;
    if (input.conversationId !== "new") return;
    if (input.messageCount > 0) return;
    postMobileHost({ type: "blank-ready" });
  }, [ready, input.conversationId, input.messageCount]);
}
