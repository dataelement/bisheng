/**
 * F004 (T046) — per-conversation run store for the unified agent runtime.
 *
 * The conversation page reads the progress of a run (answer text, thinking,
 * tool calls, plan, files, pending question, queued messages) from this store
 * only. One SSE subscription (`GET /api/v1/workstation/conversations/{id}/events`)
 * feeds it through `applyEvent`. The store never does HTTP (C7) and does not
 * mirror Recoil `linsightMapState` (design 决策 11): the `/linsight/:id` page
 * keeps its own Recoil state.
 *
 * Event contract: design §4.3 and backend
 * `bisheng/linsight/domain/schemas/run_events.py`.
 *
 * Run keying: one conversation has at most one current run. Events of an older
 * run may still be in the stream until the next `run_started`, and a send
 * response may name a new run before its `run_started` arrives. An event whose
 * `run_id` belongs to a run that was replaced is ignored, so a stale event never
 * changes the current run.
 */
import { create } from 'zustand';
import type {
    RunAskUserData,
    RunEvent,
    RunEventType,
    RunFailedData,
    RunFileData,
    RunPlanItem,
    RunResyncData,
    RunSendResult,
    RunSteerData,
    RunTextData,
} from './runEventTypes';
import { answerFilesOf, type RunAnswerFile } from './runAnswerFiles';
import { planProgressOf, type PlanProgress } from './runPlanProgress';
import {
    reduceClearDraftReturn,
    reduceResolveReturned,
    reduceUnreadMessages,
    unreadMessagesOf,
    type RunUnreadMessage,
} from './runUnread';

export * from './runEventTypes';
export * from './runSelectors';
export { planProgressOf, type PlanProgress, type RunAnswerFile, type RunUnreadMessage };

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export type RunStatus = 'running' | 'waiting' | 'stopped' | 'failed' | 'finished';

export interface ThinkingSegment {
    /** `${namespace}|${call_id}`; one segment per contiguous thinking block. */
    key: string;
    callId: string | null;
    namespace: string | null;
    text: string;
    /** Arrival rank among the thinking segments and tool calls of the run. */
    order: number;
}

export interface RunToolCall {
    callId: string;
    name: string;
    status: 'running' | 'done';
    stepType: string;
    callReason: string;
    params: unknown;
    output: string | null;
    extraInfo: Record<string, unknown>;
    order: number;
}

export interface RunState {
    runId: string;
    status: RunStatus;
    text: string;
    thinking: ThinkingSegment[];
    toolCalls: RunToolCall[];
    plan: RunPlanItem[];
    files: RunFileData[];
    pendingQuestion: RunAskUserData | null;
    /** Position in the deep-research worker queue (AC-36); null once work starts. */
    queuePosition: number | null;
    error: RunFailedData | null;
    /**
     * Files of the stored answer row (`answer_files` of the terminal event),
     * with the row's ids. Null until the run ended, and when the terminal
     * event named none (the history then supplies the row's files).
     */
    answerFiles: RunAnswerFile[] | null;
}

export interface ConversationRunState {
    run: RunState | null;
    /** Runs replaced by a newer run of this conversation; their events are ignored. */
    retiredRunIds: string[];
    /**
     * Last state of the runs another run took the place of, until the page has
     * frozen their answer rows (`clearReplacedRuns`). The current run no longer
     * describes those rows, so their content has to come from here.
     */
    replacedRuns: RunState[];
    /**
     * Number of `resync` events applied. A resync means events were missed,
     * `steer_read` possibly among them: the page then asks the history which
     * messages still wait (`clearQueuedMessages`).
     */
    resyncCount: number;
    /** Messages sent while a run was busy and not yet read by the agent (AC-13/14). */
    queuedMessages: Record<string, true>;
    /** Cursor for `Last-Event-ID` on reconnect. */
    lastEventId: string | null;
    /** Unread messages the backend gave back, until the page removed their rows. */
    returnedMessages: RunUnreadMessage[];
    /** `message_id`s already taken from `unread_messages` (event and stop response both deliver). */
    returnedIds: string[];
    /** Returned text on its way into the input box. */
    draftReturn: string | null;
}

const MAX_RETIRED_RUN_IDS = 20;
/** The page clears the list as soon as it renders; the cap only bounds a conversation that is not on screen. */
const MAX_REPLACED_RUNS = 4;

export function emptyConversationRunState(): ConversationRunState {
    return {
        run: null,
        retiredRunIds: [],
        replacedRuns: [],
        resyncCount: 0,
        queuedMessages: {},
        lastEventId: null,
        returnedMessages: [],
        returnedIds: [],
        draftReturn: null,
    };
}

function newRun(runId: string): RunState {
    return {
        runId,
        status: 'running',
        text: '',
        thinking: [],
        toolCalls: [],
        plan: [],
        files: [],
        pendingQuestion: null,
        queuePosition: null,
        error: null,
        answerFiles: null,
    };
}

function isActive(status: RunStatus | undefined): boolean {
    return status === 'running' || status === 'waiting';
}

function retire(conv: ConversationRunState, runId: string | undefined): string[] {
    if (runId === undefined || conv.retiredRunIds.includes(runId)) return conv.retiredRunIds;
    return [...conv.retiredRunIds, runId].slice(-MAX_RETIRED_RUN_IDS);
}

/** `conv.run` gives way to another run: keep its last state for the page (`replacedRuns`). */
function replacedBy(conv: ConversationRunState, nextRunId: string): RunState[] {
    if (!conv.run || conv.run.runId === nextRunId) return conv.replacedRuns;
    return [...conv.replacedRuns, conv.run].slice(-MAX_REPLACED_RUNS);
}

/** Compare two Redis Stream entry ids (`<ms>-<seq>`). Unparsable ids compare equal. */
export function compareEntryIds(a: string, b: string): number {
    const pa = a.split('-');
    const pb = b.split('-');
    const ma = Number(pa[0]);
    const mb = Number(pb[0]);
    const sa = Number(pa[1] ?? 0);
    const sb = Number(pb[1] ?? 0);
    if ([ma, mb, sa, sb].some((n) => Number.isNaN(n))) return 0;
    if (ma !== mb) return ma < mb ? -1 : 1;
    if (sa !== sb) return sa < sb ? -1 : 1;
    return 0;
}

// ---------------------------------------------------------------------------
// Pure reducers
// ---------------------------------------------------------------------------

function withRun(conv: ConversationRunState, run: RunState): ConversationRunState {
    return { ...conv, run };
}

function thinkingKey(data: RunTextData): string {
    return `${data.namespace ?? ''}|${data.call_id ?? ''}`;
}

function reduceIntoRun(run: RunState, event: RunEvent): RunState {
    switch (event.type) {
        case 'run_started':
            return run;
        case 'text': {
            const delta = event.data?.text ?? '';
            if (!delta) return run;
            return { ...run, text: run.text + delta, queuePosition: null };
        }
        case 'thinking': {
            const delta = event.data?.text ?? '';
            if (!delta) return run;
            const key = thinkingKey(event.data);
            const idx = run.thinking.findIndex((s) => s.key === key);
            const thinking =
                idx === -1
                    ? [
                          ...run.thinking,
                          {
                              key,
                              callId: event.data.call_id ?? null,
                              namespace: event.data.namespace ?? null,
                              text: delta,
                              order: run.thinking.length + run.toolCalls.length,
                          },
                      ]
                    : run.thinking.map((s, i) => (i === idx ? { ...s, text: s.text + delta } : s));
            return { ...run, thinking, queuePosition: null };
        }
        case 'tool_call': {
            const d = event.data;
            if (!d?.call_id) return run;
            const idx = run.toolCalls.findIndex((t) => t.callId === d.call_id);
            const prev = idx === -1 ? null : run.toolCalls[idx];
            const merged: RunToolCall = {
                callId: d.call_id,
                name: d.name || prev?.name || '',
                status: d.status === 'end' ? 'done' : prev?.status === 'done' ? 'done' : 'running',
                stepType: d.step_type ?? prev?.stepType ?? 'tool',
                callReason: d.call_reason || prev?.callReason || '',
                params: d.params !== undefined && d.params !== null ? d.params : prev?.params ?? null,
                output: d.output !== undefined && d.output !== null ? d.output : prev?.output ?? null,
                extraInfo: { ...(prev?.extraInfo ?? {}), ...(d.extra_info ?? {}) },
                order: prev?.order ?? run.thinking.length + run.toolCalls.length,
            };
            const toolCalls =
                idx === -1 ? [...run.toolCalls, merged] : run.toolCalls.map((t, i) => (i === idx ? merged : t));
            return { ...run, toolCalls, queuePosition: null };
        }
        case 'plan':
            return { ...run, plan: [...(event.data?.items ?? [])], queuePosition: null };
        case 'file': {
            const f = event.data;
            if (!f?.file_id) return run;
            const idx = run.files.findIndex((x) => x.file_id === f.file_id);
            const files = idx === -1 ? [...run.files, f] : run.files.map((x, i) => (i === idx ? f : x));
            return { ...run, files };
        }
        case 'ask_user':
            return { ...run, status: 'waiting', pendingQuestion: event.data ?? null };
        case 'ask_user_answered':
            return { ...run, status: isActive(run.status) ? 'running' : run.status, pendingQuestion: null };
        case 'queued':
            return { ...run, queuePosition: typeof event.data?.position === 'number' ? event.data.position : null };
        case 'run_finished':
        case 'run_stopped':
            return {
                ...run,
                status: event.type === 'run_finished' ? 'finished' : 'stopped',
                pendingQuestion: null,
                queuePosition: null,
                answerFiles: answerFilesOf(event.data),
            };
        case 'run_failed':
            return {
                ...run,
                status: 'failed',
                pendingQuestion: null,
                queuePosition: null,
                error: event.data ?? null,
                answerFiles: answerFilesOf(event.data),
            };
        default:
            return run;
    }
}

/**
 * Status of a run after a `resync`. `ended` says the run already wrote its
 * terminal event, and `status` how. For a run that has not ended, a pending
 * question means it waits for the user, otherwise it is running.
 */
function resyncStatus(d: Partial<RunResyncData>): RunStatus {
    if (d.ended) return d.status === 'failed' || d.status === 'stopped' ? d.status : 'finished';
    return d.pending_question ? 'waiting' : 'running';
}

/**
 * Thinking of a run after a resync. The snapshot holds the thinking of the
 * whole run as one string, in arrival order. A reader that already follows the
 * run received a prefix of it, so its segments stay and only the part it missed
 * is added as one more segment. Without a local run the string is one segment.
 */
function resyncThinking(prev: RunState | null, full: string): ThinkingSegment[] {
    const segment = (text: string, order: number): ThinkingSegment => ({
        key: `resync:${order}`,
        callId: null,
        namespace: null,
        text,
        order,
    });
    const known = prev ? prev.thinking.reduce((n, s) => n + s.text.length, 0) : 0;
    if (!prev || full.length < known) return full ? [segment(full, 0)] : [];
    const missed = full.slice(known);
    return missed ? [...prev.thinking, segment(missed, prev.thinking.length + prev.toolCalls.length)] : prev.thinking;
}

/**
 * Take the accumulated state of a `resync` event as the state of run `runId`.
 * The snapshot holds text, thinking, plan, files and the pending question; it
 * does not hold tool calls. The tool calls this reader already received for the
 * same run are therefore kept (the ones it missed stay unknown until the stored
 * turn replaces the row). For another run, nothing local carries over.
 */
export function reduceResync(
    conv: ConversationRunState,
    runId: string,
    data: Partial<RunResyncData> | null | undefined,
    entryId?: string | null,
): ConversationRunState {
    const d = data ?? {};
    const prev = conv.run && conv.run.runId === runId ? conv.run : null;
    const run: RunState = {
        ...newRun(runId),
        status: resyncStatus(d),
        text: d.text ?? '',
        thinking: resyncThinking(prev, d.thinking ?? ''),
        toolCalls: prev ? prev.toolCalls : [],
        plan: [...(d.plan ?? [])],
        files: dedupeFiles(d.files ?? []),
        pendingQuestion: d.ended ? null : (d.pending_question ?? null),
    };
    // The terminal event this reader missed gave messages back (a stop, or a
    // relay run that could not be created): take them as the event would have
    // delivered them, once per `message_id`.
    const returned = d.ended ? unreadMessagesOf(d) : [];
    if (returned.length && run.status === 'failed') {
        // The page tells a failed relay from other failures by this field.
        run.error = { unread_messages: returned } as RunFailedData;
    }
    const base = returned.length ? reduceUnreadMessages(conv, returned) : conv;
    const retired = prev || !conv.run ? conv.retiredRunIds : retire(conv, conv.run.runId);
    return {
        ...base,
        run,
        retiredRunIds: retired.filter((id) => id !== runId),
        replacedRuns: replacedBy(conv, runId),
        resyncCount: conv.resyncCount + 1,
        lastEventId: entryId ?? conv.lastEventId,
    };
}

function dedupeFiles(files: RunFileData[]): RunFileData[] {
    const out: RunFileData[] = [];
    for (const f of files) {
        if (!f?.file_id) continue;
        const idx = out.findIndex((x) => x.file_id === f.file_id);
        if (idx === -1) out.push(f);
        else out[idx] = f;
    }
    return out;
}

/**
 * Apply one stream event to one conversation. Pure: returns a new state, or the
 * same object when nothing changed.
 */
export function reduceRunEvent(
    conv: ConversationRunState,
    event: RunEvent | { type: string; data?: unknown; run_id?: string | null },
    entryId?: string | null,
): ConversationRunState {
    const ev = event as RunEvent;
    const cursor = entryId ?? ev.id ?? null;
    const runId = ev.run_id ?? '';
    const isNewRunStart = ev.type === 'run_started' && (!conv.run || conv.run.runId !== runId);

    // A replayed entry (reconnect overlap) is applied once only.
    if (
        cursor &&
        conv.lastEventId &&
        ev.type !== 'resync' &&
        !isNewRunStart &&
        compareEntryIds(cursor, conv.lastEventId) <= 0
    ) {
        return conv;
    }
    // Messages given back by a stop or a failed relay belong to the conversation,
    // not to a run: taken whatever run the terminal event names.
    const returned = ev.type === 'run_stopped' || ev.type === 'run_failed' ? unreadMessagesOf(ev.data) : [];
    const base = returned.length ? reduceUnreadMessages(conv, returned) : conv;
    const advanced: ConversationRunState = cursor ? { ...base, lastEventId: cursor } : base;

    if (ev.type === 'resync') {
        return reduceResync(conv, runId, ev.data as RunResyncData, cursor);
    }

    // Steer flags belong to messages, not to a run: apply them whatever the run.
    if (ev.type === 'steer_accepted' || ev.type === 'steer_read') {
        const messageId = (ev.data as RunSteerData | undefined)?.message_id;
        if (!messageId) return advanced;
        const queuedMessages = { ...advanced.queuedMessages };
        if (ev.type === 'steer_accepted') queuedMessages[messageId] = true;
        else delete queuedMessages[messageId];
        return { ...advanced, queuedMessages };
    }

    if (!TYPES.has(ev.type)) return advanced;

    if (ev.type === 'run_started') {
        if (!isNewRunStart && conv.run) return advanced;
        return {
            ...advanced,
            run: newRun(runId),
            retiredRunIds: retire(conv, conv.run?.runId).filter((id) => id !== runId),
            replacedRuns: replacedBy(conv, runId),
        };
    }

    // Events of a replaced run never touch the current run.
    if (conv.retiredRunIds.includes(runId)) return advanced;

    const current = conv.run;
    if (current && runId && current.runId && current.runId !== runId) {
        // An unknown run while the current one is live is an older run whose
        // events are still in the stream: ignore. After the current run ended,
        // a new run whose `run_started` was not seen is adopted.
        if (isActive(current.status)) return advanced;
        const adopted = reduceIntoRun(newRun(runId), ev);
        return {
            ...advanced,
            run: adopted,
            retiredRunIds: retire(conv, current.runId),
            replacedRuns: replacedBy(conv, runId),
        };
    }
    if (!current) {
        return withRun(advanced, reduceIntoRun(newRun(runId), ev));
    }
    const next = reduceIntoRun(current, ev);
    return next === current ? advanced : withRun(advanced, next);
}

// Run-scoped event types (resync and steer_* are handled before this check).
const TYPES: ReadonlySet<string> = new Set<RunEventType>(
    ['run_started', 'run_finished', 'run_failed', 'run_stopped', 'queued', 'text'].concat(
        ['thinking', 'tool_call', 'plan', 'ask_user', 'ask_user_answered', 'file'],
    ) as RunEventType[],
);

/**
 * Apply the JSON answer of a send with `X-BS-Run-Protocol: 2`.
 * `queued` marks the message as waiting in the inbox (AC-13). `started` with a
 * run id that is not the current run makes it the current run, so leftover
 * events of the previous run are ignored from now on.
 */
export function reduceSendResult(conv: ConversationRunState, result: RunSendResult): ConversationRunState {
    if (result.disposition === 'queued') {
        if (!result.message_id) return conv;
        return { ...conv, queuedMessages: { ...conv.queuedMessages, [result.message_id]: true } };
    }
    if (result.disposition === 'started' && result.run_id) {
        if (conv.run && conv.run.runId === result.run_id) {
            // Answer to a pending question: the parked run continues.
            return conv.run.status === 'waiting'
                ? { ...conv, run: { ...conv.run, status: 'running', pendingQuestion: null } }
                : conv;
        }
        return {
            ...conv,
            run: newRun(result.run_id),
            retiredRunIds: retire(conv, conv.run?.runId).filter((id) => id !== result.run_id),
            replacedRuns: replacedBy(conv, result.run_id),
        };
    }
    return conv;
}

/** The page froze the answer rows of the replaced runs. */
export function reduceClearReplacedRuns(conv: ConversationRunState): ConversationRunState {
    return conv.replacedRuns.length ? { ...conv, replacedRuns: [] } : conv;
}

/** The history says these messages were read: they no longer wait in the inbox. */
export function reduceClearQueued(conv: ConversationRunState, messageIds: Iterable<string>): ConversationRunState {
    let queuedMessages: Record<string, true> | null = null;
    for (const id of messageIds) {
        if (!conv.queuedMessages[id]) continue;
        queuedMessages ??= { ...conv.queuedMessages };
        delete queuedMessages[id];
    }
    return queuedMessages ? { ...conv, queuedMessages } : conv;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export interface RunStoreState {
    conversations: Record<string, ConversationRunState>;
    /** Single entry point for stream events (SSE `id:` line → `entryId`). */
    applyEvent: (conversationId: string, event: RunEvent, entryId?: string | null) => void;
    /** Take an accumulated snapshot as the state of `runId`. */
    applyResync: (
        conversationId: string,
        runId: string,
        data: Partial<RunResyncData>,
        entryId?: string | null,
    ) => void;
    applySendResult: (conversationId: string, result: RunSendResult) => void;
    /** `unread_messages` of a stop response (the `run_stopped` event may carry the same ones). */
    applyUnreadMessages: (conversationId: string, messages: RunUnreadMessage[]) => void;
    /** The page handled the returned messages; the text of `freshIds` goes to the input box. */
    resolveReturnedMessages: (conversationId: string, freshIds: ReadonlySet<string>) => void;
    clearDraftReturn: (conversationId: string) => void;
    clearReplacedRuns: (conversationId: string) => void;
    clearQueuedMessages: (conversationId: string, messageIds: Iterable<string>) => void;
    resetConversation: (conversationId: string) => void;
}

function update(
    state: RunStoreState,
    conversationId: string,
    fn: (conv: ConversationRunState) => ConversationRunState,
): Partial<RunStoreState> | RunStoreState {
    const prev = state.conversations[conversationId] ?? emptyConversationRunState();
    const next = fn(prev);
    if (next === prev && state.conversations[conversationId]) return state;
    return { conversations: { ...state.conversations, [conversationId]: next } };
}

export const useRunStore = create<RunStoreState>()((set) => ({
    conversations: {},
    applyEvent: (conversationId, event, entryId) =>
        set((s) => update(s, conversationId, (c) => reduceRunEvent(c, event, entryId))),
    applyResync: (conversationId, runId, data, entryId) =>
        set((s) => update(s, conversationId, (c) => reduceResync(c, runId, data, entryId))),
    applySendResult: (conversationId, result) =>
        set((s) => update(s, conversationId, (c) => reduceSendResult(c, result))),
    applyUnreadMessages: (conversationId, messages) =>
        set((s) => update(s, conversationId, (c) => reduceUnreadMessages(c, messages))),
    resolveReturnedMessages: (conversationId, freshIds) =>
        set((s) => update(s, conversationId, (c) => reduceResolveReturned(c, freshIds))),
    clearDraftReturn: (conversationId) => set((s) => update(s, conversationId, reduceClearDraftReturn)),
    clearReplacedRuns: (conversationId) => set((s) => update(s, conversationId, reduceClearReplacedRuns)),
    clearQueuedMessages: (conversationId, messageIds) =>
        set((s) => update(s, conversationId, (c) => reduceClearQueued(c, messageIds))),
    resetConversation: (conversationId) =>
        set((s) => {
            if (!(conversationId in s.conversations)) return s;
            const conversations = { ...s.conversations };
            delete conversations[conversationId];
            return { conversations };
        }),
}));
