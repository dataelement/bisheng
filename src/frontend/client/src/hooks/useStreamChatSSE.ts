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
 * - "end" event:    finalize with the persisted answer (falls back to the
 *                   accumulated text when the event carries none)
 */
import { useEffect, useRef } from "react";
import { SSE } from "sse.js";
import { hideStreamingCitations, type ChatCitation } from "@bisheng/chat/citations";

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
    onFinal: (text: string, messageId?: string | number, citations?: ChatCitation[]) => void;
    /** Called on connection or parse errors */
    onError: (error: string) => void;
    /** Called when the SSE lifecycle is fully done */
    onEnd: () => void;
}

/**
 * Hook that manages SSE connection for stream-format chat.
 * Accumulates `message.content` and `message.reasoning_content` across events.
 */
export default function useStreamChatSSE(
    submission: StreamChatSSESubmission | null
) {
    const sseRef = useRef<any>(null);
    const flushRef = useRef<(() => void) | null>(null);

    useEffect(() => {
        if (!submission) return;

        const { sseUrl, payload, onStart, onMessage, onFinal, onError, onEnd } =
            submission;

        // Accumulators
        let reasoningText = "";
        let contentText = "";
        let finished = false;

        const buildFullText = (streaming = false): string => {
            const content = streaming ? hideStreamingCitations(contentText) : contentText;
            const reasoning = streaming ? hideStreamingCitations(reasoningText) : reasoningText;
            if (reasoning) {
                return `:::thinking\n${reasoning}\n:::\n${content}`;
            }
            return content;
        };
        const flush = () => {
            if (finished) return;
            finished = true;
            onMessage(buildFullText());
        };
        flushRef.current = flush;

        const sse = new SSE(sseUrl, {
            payload: JSON.stringify(payload),
            headers: { "Content-Type": "application/json" },
        });

        sseRef.current = sse;

        sse.addEventListener("open", () => {
            if (!finished) onStart();
        });

        sse.addEventListener("message", (e: MessageEvent) => {
            if (finished) return;
            try {
                const data = JSON.parse(e.data);

                if (data.type === "end") {
                    finished = true;
                    // Stream complete. The end event carries the answer as
                    // persisted, after the backend dropped citation markers it
                    // could not back — prefer it over the raw streamed text, or
                    // those markers render as broken badges until a reload.
                    // Also hand over the real persisted answer id so the caller
                    // can swap out the temporary placeholder id.
                    const finalContent = data?.message?.content;
                    if (typeof finalContent === "string") {
                        contentText = finalContent;
                    }
                    onFinal(buildFullText(), data?.message?.message_id, Array.isArray(data.citations) ? data.citations : undefined);
                    onEnd();
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
                onMessage(buildFullText(true));
            } catch (err) {
                console.error("[StreamChatSSE] Failed to parse message:", err);
            }
        });

        sse.addEventListener("error", (e: MessageEvent) => {
            if (finished) return;
            finished = true;
            console.error("[StreamChatSSE] SSE error event, raw data:", e?.data);
            try {
                const data = JSON.parse(e.data);
                // Try multiple fields to find the error message
                const errorMsg =
                    data?.data?.exception ||
                    data?.message ||
                    data?.detail ||
                    data?.status_message ||
                    data?.text ||
                    data?.error ||
                    (typeof data === "string" ? data : JSON.stringify(data));
                onError(errorMsg);
            } catch {
                console.error("[StreamChatSSE] Could not parse error data");
                onError(e?.data || "Connection error");
            }
            onEnd();
        });

        sse.addEventListener("cancel", () => {
            if (finished) return;
            flush();
            onEnd();
        });

        sse.stream();

        return () => {
            finished = true;
            if (flushRef.current === flush) flushRef.current = null;
            sse.close();
            sseRef.current = null;
        };
    }, [submission]);

    /** Abort the current SSE stream */
    const abort = () => {
        if (sseRef.current) {
            flushRef.current?.();
            sseRef.current.close();
            sseRef.current = null;
        }
    };

    return { abort };
}
