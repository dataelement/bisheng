/**
 * F004 (T047) — the conversation page's side of the unified agent runtime.
 *
 * `useAiChat` owns the message list; this hook adds what the run protocol
 * needs and does nothing when `enabled` is false (a carrier outside it):
 *   - follows the run events of the open conversation (`useRunEvents`);
 *   - shows the answer of the run in progress as one row of the list;
 *   - when the run ends, freezes that row and lets the history endpoint
 *     replace the list;
 *   - sends a message with `X-BS-Run-Protocol: 2` and applies the answer;
 *   - asks the backend to stop the run.
 */
import i18next from 'i18next';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import type { ChatMessage } from '~/api/chatApi';
import { getAgentMessages } from '~/api/chatApi';
import { getLinsightSessionVersionList } from '~/api/linsight';
import { getMemoryFlagsApi, mergeMemoryFlags } from '~/api/memory';
import { translateApiErrorMessage } from '~/api/request';
import { sendRunMessage, stopConversationRun } from '~/api/runApi';
import { useRunEvents } from '~/hooks/useRunEvents';
import {
    addEndedRunRow,
    addLiveRow,
    applyBlockedSend,
    bindLiveTaskRow,
    classifySendResponse,
    dropSentMessages,
    freezeLiveRun,
    hasLiveRow,
    historyHasAnswer,
    isRunActive,
    isVersionInProgress,
    liveTaskRowCandidate,
    mergeHistoryWithQueued,
    needsLiveRow,
    readQueuedIds,
    reconcileSentMessages,
    removeReturnedMessages,
    settleReplacedRun,
    shownReturnedIds,
    withLiveRun,
} from '~/hooks/unifiedRun';
import { selectConversationRun, useRunStore, type RunState } from '~/store/runStore';
import { unreadMessagesOf } from '~/store/runUnread';
import { handedReturnedIds, rememberHandedReturnedIds } from '~/utils/returnedMessageLog';

type MessagesUpdater = ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[]);

/** Waits between history reloads while the answer row of an ended run is not stored yet. */
const HISTORY_RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

export interface UseUnifiedRunOptions {
    /** The carrier sends with the run protocol (conversation page); false leaves the hook inert. */
    enabled: boolean;
    /** Conversation on screen (`"new"` for an unsaved draft). */
    conversationId: string;
    /** Bucket of that conversation in `useAiChat`. */
    bucketId: string;
    /** The bucket's rows, without the live state merged in. */
    messages: ChatMessage[];
    /** History of the conversation is being loaded. */
    isLoading: boolean;
    setMessagesFor: (bucketId: string, updater: MessagesUpdater) => void;
    /** Display name for a live answer row this hook has to create. */
    sender: string;
}

export interface UnifiedSendArgs {
    /** Request body, the same one the legacy stream sends. */
    payload: Record<string, unknown>;
    flowLeaseId?: string | null;
    /** Conversation the message was typed in (`"new"` for a draft). */
    conversationId: string;
    /** Client id of the optimistic user row. */
    userMessageId: string;
    /** Writes into the bucket of this turn (follows a draft to its real id). */
    setMessages: (updater: MessagesUpdater) => void;
    /** The server named the conversation; move the turn onto that id first. */
    onConversation: (conversationId: string) => void;
    /** The send was rejected; the optimistic rows are already gone. */
    onRejected: (message: string) => void;
}

export interface UnifiedSendResult {
    accepted: boolean;
    conversationId: string | null;
    disposition: 'started' | 'queued' | 'legacy' | 'blocked' | null;
    runId: string | null;
    /** The message answered the question the run was waiting on. */
    answered: boolean;
}

/**
 * Whether the run record `versionId` of a conversation has not ended. Asked
 * once when a conversation is opened while a run is going and its last answer
 * is a stored deep-research row. Any failure reads as "not in progress".
 */
async function isRunRecordInProgress(conversationId: string, versionId: string): Promise<boolean> {
    try {
        const versions: unknown = await getLinsightSessionVersionList(conversationId, '');
        if (!Array.isArray(versions)) return false;
        const record = versions.find((v) => String((v as { id?: unknown })?.id) === versionId) as
            | { status?: unknown }
            | undefined;
        return isVersionInProgress(record?.status);
    } catch {
        return false;
    }
}

/** Localized copy for the failure of a run; '' for a run that did not fail. */
function failureTextOf(run: RunState): string {
    if (run.status !== 'failed') return '';
    // The page gave up following the run's events (useRunEvents).
    if (run.error?.connection_lost) return String(i18next.t('workstation.chat.connection_lost'));
    return translateApiErrorMessage({ status_code: run.error?.code ?? undefined });
}

const REJECTED: UnifiedSendResult = {
    accepted: false,
    conversationId: null,
    disposition: null,
    runId: null,
    answered: false,
};

export function useUnifiedRun(options: UseUnifiedRunOptions) {
    const { enabled, conversationId, bucketId, messages, isLoading, setMessagesFor, sender } = options;
    const cid = enabled && conversationId && conversationId !== 'new' ? conversationId : '';
    const conv = useRunStore(selectConversationRun(cid));
    const run = conv?.run ?? null;
    const runId = run?.runId ?? '';
    const active = isRunActive(run);
    const { follow } = useRunEvents(cid, enabled);

    const mountedRef = useRef(true);
    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);
    const senderRef = useRef(sender);
    senderRef.current = sender;
    // Runs for which "does this run need a live row?" was already answered.
    const decidedRunsRef = useRef(new Set<string>());
    // Runs whose end was already handled (row frozen, history requested).
    const settledRunsRef = useRef(new Set<string>());

    /**
     * Rows to show for a history response: the persisted rows, the live row
     * of the run in progress when the history has no row for it, and the
     * messages that still wait in the inbox.
     */
    const composeHistory = useCallback(
        (targetCid: string, history: ChatMessage[], prev: ChatMessage[]): ChatMessage[] => {
            if (!enabled) return history;
            const state = useRunStore.getState().conversations[targetCid];
            const current = state?.run ?? null;
            let rows = history;
            if (current && isRunActive(current)) {
                if (liveTaskRowCandidate(history, current)) {
                    // The last answer is a stored deep-research row. Whether it
                    // is this run is asked from its run record (effect below).
                    decidedRunsRef.current.delete(current.runId);
                } else {
                    decidedRunsRef.current.add(current.runId);
                    rows = addLiveRow(history, current, senderRef.current);
                }
            }
            return mergeHistoryWithQueued(rows, prev, state?.queuedMessages);
        },
        [enabled],
    );

    const reloadHistory = useCallback(
        (targetCid: string, endedRunId: string | null, attempt = 0) => {
            const retry = () => {
                if (!endedRunId || attempt >= HISTORY_RETRY_DELAYS_MS.length) return;
                setTimeout(() => {
                    if (mountedRef.current) reloadHistory(targetCid, endedRunId, attempt + 1);
                }, HISTORY_RETRY_DELAYS_MS[attempt]);
            };
            getAgentMessages(targetCid)
                .then((history) => {
                    if (!mountedRef.current) return;
                    // The answer row is written when the run ends; until it is
                    // there the frozen live row stays on screen.
                    if (endedRunId && !historyHasAnswer(history)) {
                        retry();
                        return;
                    }
                    const store = useRunStore.getState();
                    store.clearQueuedMessages(
                        targetCid,
                        readQueuedIds(history, store.conversations[targetCid]?.queuedMessages),
                    );
                    setMessagesFor(targetCid, (prev) =>
                        // A newer send or run owns the list now; its own end reloads it.
                        prev.some((m) => m.liveRunId !== undefined) ? prev : composeHistory(targetCid, history, prev),
                    );
                    getMemoryFlagsApi(targetCid)
                        .then((flags) => {
                            if (mountedRef.current) setMessagesFor(targetCid, (prev) => mergeMemoryFlags(prev, flags));
                        })
                        .catch(() => {
                            /* flags are decoration; the history stays usable without them */
                        });
                })
                .catch(retry);
        },
        [composeHistory, setMessagesFor],
    );

    // A run this page did not start (opened mid-run, relay run): give it a row.
    const messagesRef = useRef(messages);
    messagesRef.current = messages;
    useEffect(() => {
        if (!cid || !run || !active || isLoading || bucketId !== cid) return;
        if (decidedRunsRef.current.has(run.runId)) return;
        // A send in flight decides for its own run when the answer arrives.
        if (messagesRef.current.some((m) => m.liveRunId === '')) return;
        decidedRunsRef.current.add(run.runId);
        const candidate = liveTaskRowCandidate(messagesRef.current, run);
        if (!candidate) {
            if (needsLiveRow(messagesRef.current, run)) {
                setMessagesFor(cid, (prev) => addLiveRow(prev, run, senderRef.current));
            }
            return;
        }
        // T061: a deep-research turn is stored from its start. When its run
        // record has not ended, that stored row shows the run (from the run
        // store, no task WebSocket). Otherwise the row is an earlier turn and
        // the run gets a row of its own.
        const liveRunId = run.runId;
        void isRunRecordInProgress(cid, candidate.versionId).then((inProgress) => {
            if (!mountedRef.current) return;
            setMessagesFor(cid, (prev) => {
                const current = useRunStore.getState().conversations[cid]?.run ?? null;
                if (!current || current.runId !== liveRunId || !isRunActive(current)) return prev;
                if (inProgress) return bindLiveTaskRow(prev, candidate.versionId, liveRunId);
                return addLiveRow(prev, current, senderRef.current);
            });
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps -- asked once per run, not on every delta
    }, [cid, bucketId, runId, active, isLoading, setMessagesFor]);

    // Another run took the place of a run (a relay run after a direct answer,
    // or a new run started by a send) before this page saw the old one end.
    // The store no longer describes the old run's row, so the row is frozen
    // with the last state the store kept for it. The new run owns the list
    // from here; its own end reloads the history.
    const replacedCount = conv?.replacedRuns.length ?? 0;
    useEffect(() => {
        if (!cid || replacedCount === 0 || bucketId !== cid) return;
        const store = useRunStore.getState();
        const replaced = store.conversations[cid]?.replacedRuns ?? [];
        store.clearReplacedRuns(cid);
        const ended = replaced.map(settleReplacedRun);
        for (const old of ended) settledRunsRef.current.add(old.runId);
        setMessagesFor(cid, (prev) => ended.reduce((rows, old) => freezeLiveRun(rows, old, failureTextOf(old)), prev));
    }, [cid, bucketId, replacedCount, setMessagesFor]);

    // A resync means events were missed, possibly the `steer_read` that clears
    // a "queued" mark. The snapshot does not say which messages still wait;
    // the stored rows do.
    const resyncCount = conv?.resyncCount ?? 0;
    useEffect(() => {
        if (!cid || resyncCount === 0) return undefined;
        if (Object.keys(useRunStore.getState().conversations[cid]?.queuedMessages ?? {}).length === 0) return undefined;
        let current = true;
        getAgentMessages(cid)
            .then((history) => {
                if (!current) return;
                const store = useRunStore.getState();
                store.clearQueuedMessages(cid, readQueuedIds(history, store.conversations[cid]?.queuedMessages));
            })
            .catch(() => {
                /* the marks stay as they are; the history reload at the end of the run clears them */
            });
        return () => {
            current = false;
        };
    }, [cid, resyncCount]);

    // The run ended: keep its final state on screen, then take the stored turn.
    const liveRowPresent = !!runId && hasLiveRow(messages, runId);
    useEffect(() => {
        if (!cid || !run || active || !liveRowPresent || bucketId !== cid) return;
        if (settledRunsRef.current.has(run.runId)) return;
        settledRunsRef.current.add(run.runId);
        setMessagesFor(cid, (prev) => freezeLiveRun(prev, run, failureTextOf(run)));
        // A relay run that could not be created stored nothing and its questions
        // were deleted: the history would replace the failure row with the
        // previous turn, so the failure stays on screen as it is.
        if (run.status === 'failed' && unreadMessagesOf(run.error).length > 0) return;
        reloadHistory(cid, run.runId);
        // eslint-disable-next-line react-hooks/exhaustive-deps -- reacts to the end of the run only
    }, [cid, bucketId, runId, active, liveRowPresent, setMessagesFor, reloadHistory]);

    // Unread messages given back (the user stopped the run, or a relay run
    // could not be created): their rows leave the list and their text goes to
    // the input box. The rows may already be gone (the server deletes them, so
    // a history reload that came first shows none), which is why the text does
    // not depend on them. A message this browser handed over before is skipped:
    // the stream replays an ended run on every later visit.
    const returnedCount = conv?.returnedMessages.length ?? 0;
    useEffect(() => {
        if (!cid || returnedCount === 0 || isLoading || bucketId !== cid) return;
        const store = useRunStore.getState();
        const returned = store.conversations[cid]?.returnedMessages ?? [];
        const ids = returned.map((m) => m.message_id);
        const shown = shownReturnedIds(messagesRef.current, ids);
        if (shown.size > 0) {
            const ended = store.conversations[cid]?.run ?? null;
            // A relay run that failed before it was seen running has no row yet.
            const failedRelay = ended?.status === 'failed' && unreadMessagesOf(ended.error).length > 0 ? ended : null;
            if (failedRelay) settledRunsRef.current.add(failedRelay.runId);
            setMessagesFor(cid, (prev) => {
                const rows = removeReturnedMessages(prev, shown);
                if (!failedRelay) return rows;
                return addEndedRunRow(rows, failedRelay, senderRef.current, failureTextOf(failedRelay));
            });
        }
        const handed = handedReturnedIds();
        const fresh = new Set(ids.filter((id) => !handed.has(id)));
        rememberHandedReturnedIds(fresh);
        store.resolveReturnedMessages(cid, fresh);
    }, [cid, bucketId, returnedCount, isLoading, setMessagesFor]);

    const liveMessages = useMemo(
        () => (cid && bucketId === cid ? withLiveRun(messages, run) : messages),
        [cid, bucketId, messages, run],
    );

    const send = useCallback(
        async (args: UnifiedSendArgs): Promise<UnifiedSendResult> => {
            const reject = (message: string): UnifiedSendResult => {
                args.setMessages((prev) => dropSentMessages(prev, args.userMessageId));
                args.onRejected(message);
                return REJECTED;
            };
            let raw: unknown;
            try {
                raw = await sendRunMessage(args.payload, { flowLeaseId: args.flowLeaseId });
            } catch (err) {
                const message = (err as { message?: string } | null)?.message;
                return reject(message || translateApiErrorMessage(null));
            }
            const outcome = classifySendResponse(raw);
            if (outcome.kind === 'invalid') return reject(translateApiErrorMessage(null));

            if (outcome.kind === 'legacy') {
                // No run started (a blocked input is stored as a normal turn):
                // the stored turn is the answer.
                const legacyCid =
                    outcome.conversationId || (args.conversationId !== 'new' ? args.conversationId : '');
                if (outcome.error && !outcome.conversationId) {
                    return reject(
                        translateApiErrorMessage({
                            status_code: outcome.error.code,
                            status_message: outcome.error.message,
                        }),
                    );
                }
                if (!legacyCid) return reject(translateApiErrorMessage(null));
                args.onConversation(legacyCid);
                args.setMessages((prev) => prev.filter((m) => m.liveRunId !== ''));
                reloadHistory(legacyCid, null);
                return { accepted: true, conversationId: legacyCid, disposition: 'legacy', runId: null, answered: false };
            }

            if (outcome.kind === 'blocked') {
                // Content safety blocked the input: the turn is stored with the
                // auto-reply, no run starts and no event is written, so the
                // event stream is not followed and the conversation stays idle.
                const { blocked } = outcome;
                args.onConversation(blocked.conversationId);
                args.setMessages((prev) =>
                    applyBlockedSend(prev, blocked, { userMessageId: args.userMessageId, sender: senderRef.current }),
                );
                return {
                    accepted: true,
                    conversationId: blocked.conversationId,
                    disposition: 'blocked',
                    runId: null,
                    answered: false,
                };
            }

            const { result } = outcome;
            const targetCid = result.conversation_id || (args.conversationId !== 'new' ? args.conversationId : '');
            if (!targetCid) return reject(translateApiErrorMessage(null));
            const store = useRunStore.getState();
            const before = store.conversations[targetCid]?.run ?? null;
            const runKnown = !!before && before.runId === result.run_id;
            const answered = runKnown && before?.status === 'waiting' && outcome.kind === 'started';
            args.onConversation(targetCid);
            if (outcome.kind === 'started') decidedRunsRef.current.add(result.run_id);
            args.setMessages((prev) =>
                reconcileSentMessages(prev, outcome, {
                    userMessageId: args.userMessageId,
                    sender: senderRef.current,
                    runKnown,
                    answered,
                }),
            );
            // `queued` marks the message; `started` makes the run current, or
            // clears the pending question when the message answered it.
            store.applySendResult(targetCid, result);
            follow();
            return {
                accepted: true,
                conversationId: targetCid,
                disposition: outcome.kind,
                runId: result.run_id,
                answered,
            };
        },
        [follow, reloadHistory],
    );

    /** Ask the backend to stop the run of the open conversation. */
    const stopRun = useCallback(async (): Promise<void> => {
        if (!cid) return;
        const current = useRunStore.getState().conversations[cid]?.run ?? null;
        if (!isRunActive(current)) return;
        const result = await stopConversationRun(cid, current?.runId);
        // A run without a live execution was ended by the request itself; the
        // `run_stopped` event may carry the same messages (taken once by id).
        const unread = unreadMessagesOf(result);
        if (unread.length > 0) useRunStore.getState().applyUnreadMessages(cid, unread);
    }, [cid]);

    /** True when the run store already shows a run in progress for `targetCid`. */
    const isBusy = useCallback(
        (targetCid: string) => enabled && isRunActive(useRunStore.getState().conversations[targetCid]?.run ?? null),
        [enabled],
    );

    return {
        /** Rows to render: the bucket with the live run merged in. */
        messages: liveMessages,
        /** A run of this conversation is in progress (running or waiting for an answer). */
        isRunning: !!cid && active,
        isBusy,
        composeHistory,
        send,
        stopRun,
    };
}
