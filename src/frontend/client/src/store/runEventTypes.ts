/**
 * F004 — event and send-response types of the unified agent runtime.
 * Mirror of backend `bisheng/linsight/domain/schemas/run_events.py`;
 * re-exported by `runStore`.
 */
import type { RunUnreadMessage } from './runUnread';

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
    /** A relay run that could not be created gives its messages back (design §7 item 1). */
    unread_messages?: RunUnreadMessage[];
    /**
     * Set only by this client, never by the backend: the page gave up following
     * the run's events (useRunEvents), so it shows the run as "connection lost".
     */
    connection_lost?: boolean;
}

/** `run_stopped`: the user stopped the run; not a failure (design §7 items 2, 6). */
export interface RunStoppedData {
    reason?: string;
    status?: 'stopped';
    unread_messages?: RunUnreadMessage[];
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
    /**
     * With `ended`: the messages the terminal event gave back (a stop, or a
     * relay run that could not be created). Absent when there were none.
     */
    unread_messages?: RunUnreadMessage[];
}

export interface RunEventDataMap {
    run_started: Record<string, unknown>;
    run_finished: Record<string, unknown>;
    run_failed: RunFailedData;
    run_stopped: RunStoppedData;
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
    disposition: string;
    message_id: string;
    conversation_id?: string;
}

export const TERMINAL_RUN_EVENT_TYPES: ReadonlySet<string> = new Set(['run_finished', 'run_failed', 'run_stopped']);
