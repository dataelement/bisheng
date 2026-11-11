import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useClientEnvironment } from "~/hooks/useClientEnvironment";
import { useStartNewChat } from "~/components/Nav/NewChat";
import { readNewChatKey } from './newChatDraft';

/** Explicit presentation routes; APIs retain authorization ownership. */
export function isDesktopNavigationPath(path: string): boolean {
  return (
    /^\/c\/new\?projectId=[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$/.test(path) ||
    /^\/settings\/(?:account|desktop-usage|ai-access|my-tasks|my-requests|notifications)\?dshSettings=1$/.test(
      path,
    ) ||
    /^\/(?:c\/[a-zA-Z0-9_-]+|linsight\/[a-zA-Z0-9_-]+|chat\/[a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+\/(?:1|5|10)|knowledge|channel|apps(?:\/[a-zA-Z0-9_-]+)*|skills|square)$/.test(
      path,
    ) ||
    /^\/menu-unavailable\?plugin=(?:home|knowledge_space|subscription|apps)$/.test(
      path,
    )
  );
}

/** Presentation-only navigation; the server still authorizes every conversation. */
export function useDesktopNavigation() {
  const navigate = useNavigate();
  const location = useLocation();
  const locationRef = useRef(location);
  locationRef.current = location;
  const draftRef = useRef<{ path: string; state: { newChatKey: string } }>();
  if (location.pathname === '/c/new') draftRef.current = {
    path: location.pathname + location.search,
    state: { ...(location.state && typeof location.state === 'object' ? location.state : {}), newChatKey: readNewChatKey(location.state, location.key) },
  };
  const startNewChat = useStartNewChat();
  const { channel } = useClientEnvironment();
  useEffect(() => {
    if (channel !== "desktop") return;
    const receive = (event: Event) => {
      const path: unknown = (event as CustomEvent<{ path?: unknown }>).detail
        ?.path;
      const resetDraft = (event as CustomEvent<{ resetDraft?: unknown }>).detail?.resetDraft === true;
      if (typeof path !== "string" || !isDesktopNavigationPath(path)) return;
      event.preventDefault();
      if (resetDraft && (path === '/c/new' || path.startsWith('/c/new?'))) {
        // A new draft is an operation, even when its URL matches the last one.
        // Settings returning to the same draft sends no reset intent and keeps
        // its composer. Explicit new-chat actions share the web lifecycle.
        startNewChat(new URLSearchParams(path.split('?')[1] ?? '').get('projectId') ?? undefined);
      } else {
        const current = locationRef.current;
        if (current.pathname + current.search === path) return;
        const previousDraft = draftRef.current;
        if (previousDraft?.path === path) navigate(path, { state: previousDraft.state });
        else navigate(path);
      }
    };
    window.addEventListener("dsh:navigate", receive);
    return () => window.removeEventListener("dsh:navigate", receive);
  }, [navigate, startNewChat, channel]);
}
