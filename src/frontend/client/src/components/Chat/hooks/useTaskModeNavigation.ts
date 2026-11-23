import type { UseTaskModeNavigationOptions } from "./chatSurfaceTypes";
import { useEffect } from "react";
import {
  preserveTaskModeChoice,
  resolveTaskModeOnNavigation,
} from "~/components/Chat/resolveTaskMode";

export function useTaskModeNavigation({
  location,
  conversationId,
  setTaskMode,
  keepTaskModeOnRewriteRef,
  userToggledRef,
  lastConversationIdRef,
  canUseTaskMode,
  isTaskConversation,
}: UseTaskModeNavigationOptions) {
  // F035: sync the task-mode toggle to navigation. ChatView is NOT remounted
  // across `/c/:id` param changes (same route element), so the atom's initial
  // value only applies on first mount. This effect picks up subsequent
  // navigations:

  //  - the first submit on /c/new self-rewrites the URL to the real id; that is
  //    the SAME conversation, so the user's chosen mode is preserved (they can
  //    keep composing task turns, or toggle off manually).
  //  - any OTHER navigation to an existing conversation (id !== 'new') DERIVES
  //    the mode from that conversation's own history (isTaskConversation), so a
  //    stale mode from another tab can't leak in AND a task conversation keeps
  //    its mode.
  // Deriving and resetting MUST stay in one effect. They used to be two: the
  // reset (`setTaskMode(false)`) ran on every location.key change, while the
  // restore's deps — [conversationId, isTaskConversation, canUseTaskMode] — are
  // all constant within a visit, so it could never fire a second time. A single

  // current pathname) therefore parked the toggle on off for good, and
  // `taskMode || taskRunning` below kept the button lit until the running task
  // ended — so the drop was invisible and the NEXT turn silently went daily.
  // Placed after isTaskConversation on purpose: it is in the dep array.
  useEffect(() => {
    // Only consumable once we are ON the rewritten URL. This effect is declared
    // AFTER the effect that raises the flag (it has to be — isTaskConversation is
    // in its dep array), so within the commit that raises it we would otherwise
    // eat the flag while still on /c/new and then derive `false` on the real
    // landing, knocking the user out of the mode they just submitted in.
    const isSelfRewrite =
      conversationId !== "new" && keepTaskModeOnRewriteRef.current;
    userToggledRef.current = preserveTaskModeChoice(
      lastConversationIdRef.current,
      conversationId,
      isSelfRewrite,
      userToggledRef.current,
    );
    lastConversationIdRef.current = conversationId;
    if (isSelfRewrite) {
      keepTaskModeOnRewriteRef.current = false;
    }

    const next = resolveTaskModeOnNavigation({
      conversationId,
      isTaskConversation,
      canUseTaskMode,
      navTaskMode: (location.state as { taskMode?: boolean } | null)?.taskMode,
      isSelfRewrite,
      userToggled: userToggledRef.current,
    });
    if (next !== null) {
      setTaskMode(next);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key, conversationId, isTaskConversation, canUseTaskMode]);
}
