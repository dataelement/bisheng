/**
 * Generic SSE hook for the "stream" chat format used by channel, file, and folder chat.
 *
 * Event format:
 *   event: message
 *   data: {
 *     is_bot: boolean,
 *     message: { content: string, reasoning_content: string },
 *     type: "stream" | "end",
 *     category: "stream" | "answer",
 *     ...
 *   }
 *
 * - "stream" events: accumulate content + reasoning_content
 * - "end" event:    finalize with the full accumulated text
 */
import { useEffect, useRef } from "react";
import { SSE } from "sse.js";
import { translateApiErrorMessage } from "~/api/request";

export interface StreamChatSSESubmission {
    /** SSE endpoint URL (absolute) */
    sseUrl: string;
    /** Payload sent as POST body */
    payload: Record<string, any>;
    /** Called when the SSE connection opens */
    onStart: () => void;
    /**
     * Called on every delta. `text` is the full accumulated text so far
     * (with :::thinking::: markers if reasoning_content is present).
     */
    onMessage: (text: string) => void;
    /** Called when the stream ends (type: "end") with final full text */
    onFinal: (text: string, messageId?: string | number) => void;
    /** Called on connection or parse errors */
    onError: (error: string, meta?: StreamRateLimitMetadata) => void;
    /** Called when the SSE lifecycle is fully done */
    onEnd: () => void;
}

export interface StreamRateLimitMetadata {
    errorType?: string;
    executionId?: string;
    attemptId?: string;
    recoverySubjectId?: string;
    modelId?: string | number;
    rateLimitState?: "recovering" | "busy" | "normal";
    resumeMode?: string;
}

export function createStreamEndGuard(onEnd: () => void): () => void {
    let ended = false;
    return () => {
        if (ended) return;
        ended = true;
        onEnd();
    };
}

/**
 * Hook that manages SSE connection for stream-format chat.
 * Accumulates `message.content` and `message.reasoning_content` across events.
 */
export default function useStreamChatSSE(
    submission: StreamChatSSESubmission | null
) {
    const sseRef = useRef<any>(null);
    const endRef = useRef<(() => void) | null>(null);

    useEffect(() => {
        if (!submission) return;

        const { sseUrl, payload, onStart, onMessage, onFinal, onError, onEnd } =
            submission;

        // Accumulators
        let reasoningText = "";
        let contentText = "";
        const safeEnd = createStreamEndGuard(onEnd);
        endRef.current = safeEnd;

        const buildFullText = (): string => {
            if (reasoningText) {
                return `:::thinking\n${reasoningText}\n:::\n${contentText}`;
            }
            return contentText;
        };

        const sse = new SSE(sseUrl, {
            payload: JSON.stringify(payload),
            headers: { "Content-Type": "application/json" },
        });

        sseRef.current = sse;

        sse.addEventListener("open", () => {
            onStart();
        });

        sse.addEventListener("message", (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);

                if (data.type === "end") {
                    // Stream complete — skip content (it's the full duplicate),
                    // send final accumulated text plus the real persisted answer id
                    // (backend end event) so the caller can swap out the temporary
                    // placeholder id and feedback/like targets the right row.
                    onFinal(buildFullText(), data?.message?.message_id);
                    safeEnd();
                    return;
                }

                // Extract content deltas from message object
                const msg = data.message;
                if (msg) {
                    if (msg.reasoning_content) {
                        reasoningText += msg.reasoning_content;
                    }
                    if (msg.content) {
                        contentText += msg.content;
                    }
                }

                // Intermediate stream event — send accumulated text so far
                onMessage(buildFullText());
            } catch (err) {
                console.error("[StreamChatSSE] Failed to parse message:", err);
            }
        });

        sse.addEventListener("error", (e: MessageEvent) => {
            console.error("[StreamChatSSE] SSE error event, raw data:", e?.data);
            try {
                const data = JSON.parse(e.data);
                const errorMsg =
                    translateApiErrorMessage(data) ||
                    data?.status_message ||
                    data?.message ||
                    data?.detail ||
                    data?.text ||
                    data?.error ||
                    (typeof data === "string" ? data : JSON.stringify(data));
                const payload = data?.data ?? {};
                onError(errorMsg, {
                    errorType: typeof payload.error_type === "string" ? payload.error_type : undefined,
                    executionId: typeof payload.execution_id === "string" ? payload.execution_id : undefined,
                    attemptId: typeof payload.attempt_id === "string" ? payload.attempt_id : undefined,
                    recoverySubjectId:
                        typeof payload.recovery_subject_id === "string"
                            ? payload.recovery_subject_id
                            : undefined,
                    modelId:
                        typeof payload.model_id === "string" || typeof payload.model_id === "number"
                            ? payload.model_id
                            : undefined,
                    rateLimitState:
                        payload.rate_limit_state === "normal"
                        || payload.rate_limit_state === "recovering"
                        || payload.rate_limit_state === "busy"
                            ? payload.rate_limit_state
                            : undefined,
                    resumeMode: typeof payload.resume_mode === "string" ? payload.resume_mode : undefined,
                });
            } catch {
                console.error("[StreamChatSSE] Could not parse error data");
                onError(e?.data || "Connection error");
            }
            safeEnd();
        });

        sse.addEventListener("cancel", safeEnd);
        sse.addEventListener("abort", safeEnd);

        sse.stream();

        return () => {
            sse.close();
            safeEnd();
            sseRef.current = null;
            if (endRef.current === safeEnd) endRef.current = null;
        };
    }, [submission]);

    /** Abort the current SSE stream */
    const abort = () => {
        if (sseRef.current) {
            sseRef.current.close();
            sseRef.current = null;
        }
        endRef.current?.();
        endRef.current = null;
    };

    return { abort };
}
