import { useLayoutEffect } from 'react';
import { useLocation } from 'react-router-dom';

declare global {
  interface Window {
    dshChatPresentation?: { reportLanding: (landing: boolean) => void; reportKnowledgeDialog?: (open: boolean) => void; reportNavigation?: (navigation: unknown) => void; reportSettings?: (section: string) => void; requestSettingsClose?: () => void; requestSettingsFocus?: (direction: 'previous' | 'next') => void };
  }
}

/** Use the same optimistic message state as ChatView, before the server assigns an ID. */
export function useDesktopConversation(conversationId: string, landing: boolean) {
  const { pathname } = useLocation();
  useLayoutEffect(() => {
    // KeepAlive views publish only while their own conversation route is selected.
    if (pathname === `/c/${conversationId}`) {
      window.dshChatPresentation?.reportLanding(landing);
    }
  }, [conversationId, landing, pathname]);
}
