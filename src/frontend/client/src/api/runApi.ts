/**
 * F004 (T047) — HTTP calls of the unified agent runtime.
 *
 * Backend contract: `bisheng/workstation/domain/services/run_send.py`.
 * The send endpoint is the one daily chat already uses; the header
 * `X-BS-Run-Protocol: 2` asks for the JSON answer instead of the SSE stream.
 */
import http from '~/api/request';

export const RUN_PROTOCOL_HEADER = 'X-BS-Run-Protocol';
export const RUN_PROTOCOL_V2 = '2';

const API = {
    send: () => `/api/v1/workstation/chat/completions`,
    events: (conversationId: string) =>
        `/api/v1/workstation/conversations/${encodeURIComponent(conversationId)}/events`,
    stop: (conversationId: string) => `/api/v1/workstation/conversations/${encodeURIComponent(conversationId)}/stop`,
    queuePosition: (conversationId: string) =>
        `/api/v1/workstation/conversations/${encodeURIComponent(conversationId)}/queue-position`,
    fileUrl: (conversationId: string, fileId: string) =>
        `/api/v1/workstation/conversations/${encodeURIComponent(conversationId)}/files/${encodeURIComponent(fileId)}/url`,
};

/**
 * Request options of the run calls. The backend answers a business error with
 * HTTP 200 and an error envelope. Without `skip403Redirect` the response
 * interceptor sends the whole page to /c/new on a business 403; with it, every
 * error envelope rejects with the translated message. `showError: false` keeps
 * the interceptor from showing a toast: the caller decides how to show it.
 */
const RUN_REQUEST_OPTIONS = { skip403Redirect: true, showError: false } as const;

/** Path of the endpoint that issues a link to one file of the conversation's run. */
export function getRunFileUrlPath(conversationId: string, fileId: string): string {
    return API.fileUrl(conversationId, fileId);
}

/**
 * A fresh link to a file the current run announced with a `file` event.
 * Resolves with undefined when the backend cannot issue one.
 */
export async function getRunFileUrl(conversationId: string, fileId: string): Promise<string | undefined> {
    try {
        const res: { data?: { url?: string } } = await http.get(API.fileUrl(conversationId, fileId));
        return res?.data?.url || undefined;
    } catch {
        return undefined;
    }
}

/**
 * AC-36: 1-based place of the conversation's deep-research run in the worker
 * queue, or null when nothing of the conversation waits there.
 */
export async function getRunQueuePosition(conversationId: string): Promise<number | null> {
    const res: { data?: { position?: number | null } } = await http.get(
        API.queuePosition(conversationId),
        RUN_REQUEST_OPTIONS,
    );
    const position = res?.data?.position;
    return typeof position === 'number' && position > 0 ? position : null;
}

/** Absolute URL of the run event stream (SSE) of one conversation. */
export function getRunEventsUrl(conversationId: string): string {
    const base = import.meta.env.BASE_URL?.replace(/\/$/, '') || '';
    return `${base}${API.events(conversationId)}`;
}

export interface SendRunMessageOptions {
    /** Department page lease of this session page (`X-Flow-Lease-Id`). */
    flowLeaseId?: string | null;
}

/**
 * Send one message through the unified runtime.
 *
 * Resolves with the raw response body: normally the JSON envelope
 * `{status_code, status_message, data: {run_id, disposition, message_id, conversation_id}}`.
 * A blocked input answers `disposition: "blocked"` with the auto-reply and the
 * two stored row ids, and writes no events. An older backend answers it with
 * SSE text, so the body can be a string; `classifySendResponse`
 * (hooks/unifiedRun.ts) tells the cases apart.
 * A business error envelope (for example 12045, or 403) rejects with an error
 * whose `message` is the translated copy. The request layer shows nothing and
 * does not redirect; the caller shows the message.
 */
export async function sendRunMessage(
    payload: Record<string, unknown>,
    options: SendRunMessageOptions = {},
): Promise<unknown> {
    return http.post(API.send(), payload, {
        ...RUN_REQUEST_OPTIONS,
        headers: {
            'Content-Type': 'application/json',
            [RUN_PROTOCOL_HEADER]: RUN_PROTOCOL_V2,
            ...(options.flowLeaseId ? { 'X-Flow-Lease-Id': options.flowLeaseId } : {}),
        },
    });
}

/** Answer of the stop request. `unread_messages` is filled when this request ended the run itself. */
export interface StopRunResult {
    run_id: string | null;
    /** `stopping` (the `run_stopped` event follows), `stopped`, `idle` or `expired`. */
    status: string;
    unread_messages: unknown[];
}

/**
 * Ask the backend to stop the run of a conversation. The run reports the stop
 * through a `run_stopped` event. The messages it never read come back in that
 * event, or here when the run had no live execution (design §7 item 6).
 * A business error envelope rejects with the translated message; the request
 * layer shows nothing and does not redirect.
 */
export async function stopConversationRun(conversationId: string, runId?: string | null): Promise<StopRunResult> {
    const res: { data?: Partial<StopRunResult> } | null = await http.post(
        API.stop(conversationId),
        runId ? { run_id: runId } : {},
        RUN_REQUEST_OPTIONS,
    );
    const data = res?.data;
    return {
        run_id: data?.run_id ?? null,
        status: typeof data?.status === 'string' ? data.status : '',
        unread_messages: Array.isArray(data?.unread_messages) ? data.unread_messages : [],
    };
}
