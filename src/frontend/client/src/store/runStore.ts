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

// ---------------------------------------------------------------------------
// Event types (mirror run_events.py)
// ---------------------------------------------------------------------------

export type PlanItemStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';

export interface RunPlanItem {
    /** Stays the same when the row is reworded. */
    id: string;
    content: string;
    /** Wording before the most recent rewrite (AC-10). */
    previous_content?: string | null;
    status: PlanItemStatus;
}

export interface RunTextData {
    text: string;
    /** `thinking` only: id of the contiguous thinking segment. */
    call_id?: string | null;
    /** `thinking` only: subagent namespace. */
    namespace?: string | null;
}

export interface RunToolCallData {
    call_id: string;
    name: string;
    status: 'start' | 'end';
    /** `tool` / `knowledge` / `subagent`. */
    step_type?: string;
    call_reason?: string;
    params?: unknown;
    /** End frame only. */
    output?: string | null;
    extra_info?: Record<string, unknown>;
}

export interface RunAskUserQuestion {
    question: string;
    options?: string[];
    multiple?: boolean;
    id?: string | null;
}

export interface RunAskUserData {
    call_id: string;
    reason?: string;
    questions: RunAskUserQuestion[];
}

export interface RunAskUserAnsweredData {
    call_id?: string | null;
    answer?: unknown;
}

export interface RunSteerData {
    message_id: string;
}

export interface RunFileData {
    file_id: string;
    name: string;
    path: string;
    size?: number | null;
    source?: string | null;
}

export interface RunQueuedData {
    position: number;
}

export interface RunFailedData {
    code: number;
    reason: string;
    detail: string;
    reference_id?: string | null;
    failure_info?: Record<string, unknown> | null;
}

export interface RunResyncData {
    text: string;
    thinking: string;
    plan: RunPlanItem[];
    files: RunFileData[];
    pending_question?: RunAskUserData | null;
    /** True when the run already wrote its terminal event. */
    ended?: boolean;
    /** With `ended`: how the run ended. */
    status?: 'finished' | 'failed' | 'stopped' | null;
}

export interface RunEventDataMap {
    run_started: Record<string, unknown>;
    run_finished: Record<string, unknown>;
    run_failed: RunFailedData;
    run_stopped: Record<string, unknown>;
    queued: RunQueuedData;
    text: RunTextData;
    thinking: RunTextData;
    tool_call: RunToolCallData;
    plan: { items: RunPlanItem[] };
    steer_accepted: RunSteerData;
    steer_read: RunSteerData;
    ask_user: RunAskUserData;
    ask_user_answered: RunAskUserAnsweredData;
    file: RunFileData;
    resync: RunResyncData;
}

export type RunEventType = keyof RunEventDataMap;

/** One event as the SSE `data:` line carries it. */
export type RunEvent = {
    [K in RunEventType]: {
        type: K;
        data: RunEventDataMap[K];
        /** Empty string when the writer did not pass one. */
        run_id?: string | null;
        /** Stream entry id; the SSE `id:` line carries the same value. */
        id?: string | null;
        seq?: number | null;
        ts?: number | null;
    };
}[RunEventType];

/** `data` of the send response when the request carries `X-BS-Run-Protocol: 2`. */
export interface RunSendResult {
    run_id: string;
    /** `started` (new run or an answer to a pending question) or `queued`. */
    disposition: 'started' | 'queued' | string;
    message_id: string;
    conversation_id?: string;
}

export const TERMINAL_RUN_EVENT_TYPES: ReadonlySet<string> = new Set(['run_finished', 'run_failed', 'run_stopped']);

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
}

export interface ConversationRunState {
    run: RunState | null;
    /** Runs replaced by a newer run of this conversation; their events are ignored. */
    retiredRunIds: string[];
    /** Messages sent while a run was busy and not yet read by the agent (AC-13/14). */
    queuedMessages: Record<string, true>;
    /** Cursor for `Last-Event-ID` on reconnect. */
    lastEventId: string | null;
}

const MAX_RETIRED_RUN_IDS = 20;

export function emptyConversationRunState(): ConversationRunState {
    return { run: null, retiredRunIds: [], queuedMessages: {}, lastEventId: null };
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
    };
}

function isActive(status: RunStatus | undefined): boolean {
    return status === 'running' || status === 'waiting';
}

function retire(conv: ConversationRunState, runId: string | undefined): string[] {
    if (runId === undefined || conv.retiredRunIds.includes(runId)) return conv.retiredRunIds;
    return [...conv.retiredRunIds, runId].slice(-MAX_RETIRED_RUN_IDS);
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
            return { ...run, status: 'finished', pendingQuestion: null, queuePosition: null };
        case 'run_stopped':
            return { ...run, status: 'stopped', pendingQuestion: null, queuePosition: null };
        case 'run_failed':
            return { ...run, status: 'failed', pendingQuestion: null, queuePosition: null, error: event.data ?? null };
        default:
            return run;
    }
}

/**
 * Replace the current run with the accumulated state of a `resync` event.
 * `ended` says the run already wrote its terminal event, and `status` how. For
 * a run that has not ended, a pending question means it waits for the user,
 * otherwise it is running.
 */
function resyncStatus(d: Partial<RunResyncData>): RunStatus {
    if (d.ended) return d.status === 'failed' || d.status === 'stopped' ? d.status : 'finished';
    return d.pending_question ? 'waiting' : 'running';
}

export function reduceResync(
    conv: ConversationRunState,
    runId: string,
    data: Partial<RunResyncData> | null | undefined,
    entryId?: string | null,
): ConversationRunState {
    const d = data ?? {};
    const run: RunState = {
        ...newRun(runId),
        status: resyncStatus(d),
        text: d.text ?? '',
        thinking: d.thinking ? [{ key: 'resync', callId: null, namespace: null, text: d.thinking, order: 0 }] : [],
        plan: [...(d.plan ?? [])],
        files: dedupeFiles(d.files ?? []),
        pendingQuestion: d.ended ? null : (d.pending_question ?? null),
    };
    const replaced = conv.run && conv.run.runId !== runId ? retire(conv, conv.run.runId) : conv.retiredRunIds;
    return {
        ...conv,
        run,
        retiredRunIds: replaced.filter((id) => id !== runId),
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
    const advanced: ConversationRunState = cursor ? { ...conv, lastEventId: cursor } : conv;

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
        return { ...advanced, run: adopted, retiredRunIds: retire(conv, current.runId) };
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
        };
    }
    return conv;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export interface RunStoreState {
    conversations: Record<string, ConversationRunState>;
    /** Single entry point for stream events (SSE `id:` line → `entryId`). */
    applyEvent: (conversationId: string, event: RunEvent, entryId?: string | null) => void;
    /** Replace the current run with an accumulated snapshot. */
    applyResync: (
        conversationId: string,
        runId: string,
        data: Partial<RunResyncData>,
        entryId?: string | null,
    ) => void;
    applySendResult: (conversationId: string, result: RunSendResult) => void;
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
    resetConversation: (conversationId) =>
        set((s) => {
            if (!(conversationId in s.conversations)) return s;
            const conversations = { ...s.conversations };
            delete conversations[conversationId];
            return { conversations };
        }),
}));

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

export interface PlanProgress {
    done: number;
    total: number;
}

const EMPTY_PROGRESS: PlanProgress = Object.freeze({ done: 0, total: 0 }) as PlanProgress;
// Small identity cache so a selector returns the same object while the plan
// array is unchanged (each `plan` event replaces the array).
const PROGRESS_CACHE_SIZE = 16;
const progressCache: Array<{ items: RunPlanItem[]; progress: PlanProgress }> = [];

/** Completed rows / rows (AC-08). Cancelled rows count in neither number. */
export function planProgressOf(items: RunPlanItem[] | null | undefined): PlanProgress {
    if (!items || items.length === 0) return EMPTY_PROGRESS;
    const cached = progressCache.find((entry) => entry.items === items);
    if (cached) return cached.progress;
    const live = items.filter((i) => i.status !== 'cancelled');
    const progress = { done: live.filter((i) => i.status === 'completed').length, total: live.length };
    progressCache.push({ items, progress });
    if (progressCache.length > PROGRESS_CACHE_SIZE) progressCache.shift();
    return progress;
}

export const selectConversationRun =
    (conversationId: string) =>
    (state: RunStoreState): ConversationRunState | undefined =>
        state.conversations[conversationId];

export const selectRun =
    (conversationId: string) =>
    (state: RunStoreState): RunState | null =>
        state.conversations[conversationId]?.run ?? null;

/** True from `run_started` until a terminal event, including while waiting for an answer. */
export const selectIsRunning =
    (conversationId: string) =>
    (state: RunStoreState): boolean =>
        isActive(state.conversations[conversationId]?.run?.status);

/**
 * Sending is accepted in every state (AC-12): idle starts a run, a running run
 * takes the message as a steer, a waiting run takes it as the answer.
 */
export const selectCanSend: (conversationId: string) => (state: RunStoreState) => boolean = () => () => true;

export const selectPlanProgress =
    (conversationId: string) =>
    (state: RunStoreState): PlanProgress =>
        planProgressOf(state.conversations[conversationId]?.run?.plan);

export const selectIsMessageQueued =
    (conversationId: string, messageId: string | number | null | undefined) =>
    (state: RunStoreState): boolean =>
        messageId !== null &&
        messageId !== undefined &&
        Boolean(state.conversations[conversationId]?.queuedMessages[String(messageId)]);

export const selectLastEventId =
    (conversationId: string) =>
    (state: RunStoreState): string | null =>
        state.conversations[conversationId]?.lastEventId ?? null;
