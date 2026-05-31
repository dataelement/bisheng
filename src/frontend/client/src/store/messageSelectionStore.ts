/**
 * F028 — Recoil store for the workstation conversation export "selection mode".
 *
 * The state is **intent-based** rather than snapshot-based:
 *  - ``selectedIds`` holds explicit per-message toggles.
 *  - ``globalSelectAllOn`` means "every message in the current chat is in" —
 *    including ones loaded later via scroll-up. Clearing this flag materializes
 *    the snapshot into ``selectedIds``.
 *  - ``selectAllBelowAnchor`` means "every message from this anchor downward
 *    (chronologically) is in"; same materialization rule applies.
 *
 * Resolution of "is message X selected?" lives in the pure helper
 * ``computeSelectedIds`` (see useMessageSelection.ts) which takes both the
 * state and the current visible message list as input. This keeps the store
 * free of message data and lets selection survive scroll-loaded additions
 * without polling.
 *
 * Scope: single-conversation. ``chatId`` pins the selection to its chat; on
 * conversation switch the hook auto-exits to avoid bleeding into a stranger.
 */

import { atom } from 'recoil';

export interface MessageSelectionState {
    /** Whether selection mode is active for the current conversation. */
    active: boolean;
    /** The conversation this selection belongs to. */
    chatId: string | null;
    /** Explicitly toggled message ids. */
    selectedIds: Set<string>;
    /**
     * Anchor message id captured at toggle time — used by shift-click or
     * the "select all below" interaction so consecutive ranges can be derived.
     */
    anchorMessageId: string | null;
    /** Intent flag: every message in the chat (incl. future scroll-loaded) is selected. */
    globalSelectAllOn: boolean;
    /**
     * Intent: every message at or after this anchor (chronologically) is selected.
     * Mutually exclusive with ``globalSelectAllOn`` in practice (last clicked wins).
     */
    selectAllBelowAnchor: string | null;
}

export const EMPTY_SELECTION_STATE: MessageSelectionState = {
    active: false,
    chatId: null,
    selectedIds: new Set<string>(),
    anchorMessageId: null,
    globalSelectAllOn: false,
    selectAllBelowAnchor: null,
};

export const messageSelectionAtom = atom<MessageSelectionState>({
    key: 'messageSelectionAtom',
    default: EMPTY_SELECTION_STATE,
    // Set<string> is fine in Recoil; we just disable "freeze on read" because
    // freezing a Set turns operations like .add into runtime errors. Mutating
    // a Set in place would also break Recoil's diff, so callers always replace
    // it with a new Set instead.
    dangerouslyAllowMutability: true,
});
