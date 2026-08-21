/**
 * Per-conversation draft text for the daily-chat composer.
 *
 * The composer used to hold its draft in ChatView's local `useState`. ChatView
 * is NOT remounted when the route's `conversationId` changes (and it is also
 * KeepAlive-cached), so a half-typed message leaked into whichever conversation
 * the user switched to next. Keying the draft by conversation id makes each
 * conversation own its own unsent text.
 *
 * Backed by a plain module-level Map rather than a global store: Recoil is
 * frozen (no new atoms, ledger #5) and this is neither server state nor
 * app-wide state — it is one component's scratch text, read and written by a
 * single consumer. Deliberately memory-only, no localStorage / sessionStorage:
 * a draft is a transient in-tab convenience, a page refresh is the user's own
 * "start over", and restoring text they thought they had discarded is worse
 * than losing it. Purely client UI state — never sent to the backend, issues no
 * HTTP (constitution C7).
 */
import { useCallback, useRef, useState } from 'react';

/** Unsent composer text, keyed by conversation id ('new' for the landing page). */
const drafts = new Map<string, string>();

/**
 * Draft text for one conversation.
 *
 * @param conversationId Route conversation id; 'new' while composing the first
 *                       message (the fresh conversation gets its own empty
 *                       draft once the backend promotes it to a real id).
 * @returns `[draft, setDraft]` with the same signature as `useState<string>`.
 */
export function useConversationDraft(conversationId: string): [string, (val: string) => void] {
  const [draft, setDraft] = useState(() => drafts.get(conversationId) ?? '');
  const shownIdRef = useRef(conversationId);

  // Switching conversation swaps the draft in place. Setting state during
  // render (React's documented "adjust state when a prop changes" pattern) so
  // the textarea never paints one frame of the previous conversation's text.
  if (shownIdRef.current !== conversationId) {
    shownIdRef.current = conversationId;
    setDraft(drafts.get(conversationId) ?? '');
  }

  const setConversationDraft = useCallback(
    (val: string) => {
      // Drop empty drafts so the map does not accumulate one entry per
      // conversation ever opened in this tab.
      if (val) drafts.set(conversationId, val);
      else drafts.delete(conversationId);
      setDraft(val);
    },
    [conversationId],
  );

  return [draft, setConversationDraft];
}
