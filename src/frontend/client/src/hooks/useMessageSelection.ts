/**
 * F028 — useMessageSelection hook + pure selection helpers.
 *
 * Centralizes every interaction the conversation-export "selection mode"
 * needs: enter, exit, toggle, select-all, select-all-below, and the
 * materialization that converts intent-flags (globalSelectAllOn /
 * selectAllBelowAnchor) into a concrete Set<string> against the current
 * visible message list.
 *
 * Pairing rule (spec §3 / AC-03 / AC-06): a query and its answer(s) — linked
 * by ``parentMessageId`` — always select / deselect as a group. Multi-answer
 * "regenerate" siblings (same parentMessageId) are all members of the same
 * pair group.
 *
 * Auto-exit on conversation switch (spec §3): the consumer wires up the
 * effect via ``useExitSelectionOnChatChange``.
 */

import { useCallback, useEffect, useMemo } from 'react';
import { useRecoilState, useResetRecoilState } from 'recoil';
import {
    EMPTY_SELECTION_STATE,
    type MessageSelectionState,
    messageSelectionAtom,
} from '~/store/messageSelectionStore';

/** Cap matches backend Pydantic Field(max_length=200) on ExportMessagesRequest. */
export const SELECTION_BATCH_CAP = 200;

/**
 * Minimal message shape the selection logic actually reads. Kept structural
 * (not tied to ``TMessage`` or ``ChatMessage``) because both the v2.5
 * Agent-mode ``ChatMessage`` from chatApi.ts and the canonical ``TMessage``
 * from types/chat/schemas.ts satisfy it — picking either would force noisy
 * casts at call sites.
 */
export interface SelectableMessage {
    messageId: string;
    parentMessageId?: string | null;
    isCreatedByUser?: boolean;
}

// ─── Pure helpers (exported for testing + reuse) ─────────────────────────


/**
 * Build the "pair group" for a given message: the query plus all answers
 * sharing the same parentMessageId. Falls back to a single-message group for
 * legacy data with no parentMessageId.
 */
export function buildPairGroup(
    targetId: string,
    messages: readonly SelectableMessage[],
): string[] {
    // Pair group = one query plus every assistant answer that follows it
    // before the next query, derived from array order (assumed chronological).
    //
    // Why not by ``parentMessageId``: in the workstation chat the runtime
    // ChatMessage always carries ``parentMessageId === ""`` (the field is
    // populated server-side only for forked LibreChat-style branches). Pair-
    // ing therefore has to come from positional adjacency, which is also
    // what the user actually sees on screen — answers stacked right under
    // their question.
    const targetIdx = messages.findIndex((m) => m.messageId === targetId);
    if (targetIdx === -1) return [targetId];
    const target = messages[targetIdx];

    let queryIdx: number;
    if (target.isCreatedByUser) {
        queryIdx = targetIdx;
    } else {
        // Walk backwards to the nearest preceding user message — that's the
        // question this answer (and its regenerate siblings) belongs to.
        queryIdx = -1;
        for (let i = targetIdx - 1; i >= 0; i--) {
            if (messages[i].isCreatedByUser) {
                queryIdx = i;
                break;
            }
        }
        // Orphan answer with no preceding query (legacy / corrupt data):
        // treat as its own single-member group instead of guessing.
        if (queryIdx === -1) return [targetId];
    }

    const group: string[] = [messages[queryIdx].messageId];
    for (let i = queryIdx + 1; i < messages.length; i++) {
        if (messages[i].isCreatedByUser) break;
        group.push(messages[i].messageId);
    }
    return group;
}

/**
 * Materialize the effective set of selected message ids given current state +
 * visible messages. Combines: explicit ``selectedIds``, ``globalSelectAllOn``
 * (every visible message), and ``selectAllBelowAnchor`` (anchor + all later
 * in array order, which mirrors chronological order in the chat view).
 */
export function computeSelectedIds(
    state: MessageSelectionState,
    messages: readonly SelectableMessage[],
): Set<string> {
    if (!state.active) return new Set();

    if (state.globalSelectAllOn) {
        return new Set(messages.map((m) => m.messageId));
    }

    const out = new Set<string>(state.selectedIds);

    if (state.selectAllBelowAnchor) {
        const anchorIdx = messages.findIndex(
            (m) => m.messageId === state.selectAllBelowAnchor,
        );
        if (anchorIdx >= 0) {
            for (let i = anchorIdx; i < messages.length; i++) {
                out.add(messages[i].messageId);
            }
        }
    }
    return out;
}

/** Cap check (spec AC-08): selecting more than 200 messages is blocked. */
export function isOverBatchLimit(
    state: MessageSelectionState,
    messages: readonly SelectableMessage[],
    cap: number = SELECTION_BATCH_CAP,
): boolean {
    return computeSelectedIds(state, messages).size > cap;
}

/**
 * Internal helper: when an individual toggle happens with a global/anchor
 * intent active, freeze the current snapshot into ``selectedIds`` so the
 * subsequent toggle behaves predictably (otherwise the global flag would
 * "outvote" the un-toggle).
 */
function _materialize(
    state: MessageSelectionState,
    messages: readonly SelectableMessage[],
): MessageSelectionState {
    if (!state.globalSelectAllOn && !state.selectAllBelowAnchor) return state;
    const frozen = computeSelectedIds(state, messages);
    return {
        ...state,
        selectedIds: frozen,
        globalSelectAllOn: false,
        selectAllBelowAnchor: null,
    };
}

// ─── Hook ────────────────────────────────────────────────────────────────


export interface UseMessageSelectionApi {
    state: MessageSelectionState;
    /** True when selection mode is active for the supplied chatId. */
    isActiveForChat: (chatId: string) => boolean;
    /** Enter selection mode anchored to a single message (default-select it + its pair). */
    enterSelectionMode: (chatId: string, initialMessageId: string, messages: readonly SelectableMessage[]) => void;
    /** Exit selection mode, dropping all selection state. */
    exitSelectionMode: () => void;
    /** Toggle a single message; cascades over its query/answer pair group. */
    toggleMessage: (messageId: string, messages: readonly SelectableMessage[]) => void;
    /** Activate "select every message in this chat (incl. future loads)". */
    selectAll: () => void;
    /** Activate "select every message at or after this anchor". */
    selectAllBelow: (anchorMessageId: string) => void;
    /** Test whether a given message id is currently selected. */
    isSelected: (messageId: string, messages: readonly SelectableMessage[]) => boolean;
    /** Materialized snapshot — call right before submitting export/import. */
    getSelectedIds: (messages: readonly SelectableMessage[]) => string[];
    /** True when the current selection exceeds SELECTION_BATCH_CAP. */
    isOverLimit: (messages: readonly SelectableMessage[]) => boolean;
}

export function useMessageSelection(): UseMessageSelectionApi {
    const [state, setState] = useRecoilState(messageSelectionAtom);
    const resetState = useResetRecoilState(messageSelectionAtom);

    const isActiveForChat = useCallback(
        (chatId: string) => state.active && state.chatId === chatId,
        [state.active, state.chatId],
    );

    const enterSelectionMode = useCallback(
        (chatId: string, initialMessageId: string, messages: readonly SelectableMessage[]) => {
            const group = buildPairGroup(initialMessageId, messages);
            setState({
                ...EMPTY_SELECTION_STATE,
                active: true,
                chatId,
                selectedIds: new Set(group),
                anchorMessageId: initialMessageId,
            });
        },
        [setState],
    );

    const exitSelectionMode = useCallback(() => {
        // useResetRecoilState resets to the atom's default — but our default
        // is a *shared* Set instance. Use explicit replacement so different
        // sessions never share the same Set reference.
        setState({ ...EMPTY_SELECTION_STATE, selectedIds: new Set() });
    }, [setState]);

    const toggleMessage = useCallback(
        (messageId: string, messages: readonly SelectableMessage[]) => {
            setState((prev) => {
                if (!prev.active) return prev;
                const base = _materialize(prev, messages);
                const group = buildPairGroup(messageId, messages);
                const next = new Set(base.selectedIds);
                // Cascade by group membership: if the clicked id is currently
                // selected → un-select the whole group; otherwise → select it.
                const currentlyOn = next.has(messageId);
                for (const id of group) {
                    if (currentlyOn) next.delete(id);
                    else next.add(id);
                }
                return {
                    ...base,
                    selectedIds: next,
                    anchorMessageId: messageId,
                };
            });
        },
        [setState],
    );

    const selectAll = useCallback(() => {
        setState((prev) => {
            if (!prev.active) return prev;
            return {
                ...prev,
                globalSelectAllOn: true,
                selectAllBelowAnchor: null,
                // Wipe explicit selections — global supersedes them.
                selectedIds: new Set(),
            };
        });
    }, [setState]);

    const selectAllBelow = useCallback(
        (anchorMessageId: string) => {
            setState((prev) => {
                if (!prev.active) return prev;
                return {
                    ...prev,
                    selectAllBelowAnchor: anchorMessageId,
                    globalSelectAllOn: false,
                    anchorMessageId,
                };
            });
        },
        [setState],
    );

    const isSelected = useCallback(
        (messageId: string, messages: readonly SelectableMessage[]) => {
            return computeSelectedIds(state, messages).has(messageId);
        },
        [state],
    );

    const getSelectedIds = useCallback(
        (messages: readonly SelectableMessage[]) =>
            Array.from(computeSelectedIds(state, messages)),
        [state],
    );

    const isOverLimit = useCallback(
        (messages: readonly SelectableMessage[]) => isOverBatchLimit(state, messages),
        [state],
    );

    return useMemo(
        () => ({
            state,
            isActiveForChat,
            enterSelectionMode,
            exitSelectionMode,
            toggleMessage,
            selectAll,
            selectAllBelow,
            isSelected,
            getSelectedIds,
            isOverLimit,
        }),
        [
            state, isActiveForChat, enterSelectionMode, exitSelectionMode,
            toggleMessage, selectAll, selectAllBelow, isSelected,
            getSelectedIds, isOverLimit,
        ],
    );
}

/**
 * Auto-exit selection mode whenever the active conversation changes.
 *
 * Caller pattern: in the workspace chat layout, pass the currently active
 * conversation id; we wipe the selection state if it belongs to a different
 * chat (or the user moved to no-chat).
 */
export function useExitSelectionOnChatChange(currentChatId: string | null | undefined): void {
    const { state, exitSelectionMode } = useMessageSelection();
    useEffect(() => {
        if (!state.active) return;
        if (state.chatId !== currentChatId) {
            exitSelectionMode();
        }
    }, [currentChatId, state.active, state.chatId, exitSelectionMode]);
}
