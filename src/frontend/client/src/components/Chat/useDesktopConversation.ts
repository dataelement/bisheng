import { useClientEnvironment } from "~/hooks/useClientEnvironment";
import { readDesktopPresentation } from "~/utils/clientEnvironment";
import { useLayoutEffect } from "react";
import { useLocation } from "react-router-dom";

/** Use the same optimistic message state as ChatView, before the server assigns an ID. */
export function useDesktopConversation(
  conversationId: string,
  landing: boolean,
) {
  const { pathname } = useLocation();
  const {
    channel,
    capabilities: { hasNativePresentation },
  } = useClientEnvironment();
  useLayoutEffect(() => {
    // KeepAlive views publish only while their own conversation route is selected.
    if (pathname === `/c/${conversationId}`) {
      readDesktopPresentation().reportLanding?.(landing);
    }
  }, [conversationId, landing, pathname, channel, hasNativePresentation]);
}
