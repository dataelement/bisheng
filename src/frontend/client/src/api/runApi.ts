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
};

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
 * A blocked input is still answered with today's SSE text, so the body can be
 * a string; `classifySendResponse` (hooks/unifiedRun.ts) tells the cases apart.
 * A business error rejects through the shared response interceptors.
 */
export async function sendRunMessage(
    payload: Record<string, unknown>,
    options: SendRunMessageOptions = {},
): Promise<unknown> {
    return http.post(API.send(), payload, {
        headers: {
            'Content-Type': 'application/json',
            [RUN_PROTOCOL_HEADER]: RUN_PROTOCOL_V2,
            ...(options.flowLeaseId ? { 'X-Flow-Lease-Id': options.flowLeaseId } : {}),
        },
    });
}

/**
 * Ask the backend to stop the run of a conversation. The run reports the stop
 * through a `run_stopped` event; nothing is changed locally here.
 */
export async function stopConversationRun(conversationId: string, runId?: string | null): Promise<void> {
    await http.post(API.stop(conversationId), runId ? { run_id: runId } : {});
}
