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
    onFinal: (text: string) => void;
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

    useEffect(() => {
        if (!submission) return;

        const { sseUrl, payload, onStart, onMessage, onFinal, onError, onEnd } =
            submission;

        // Accumulators
        let reasoningText = "";
        let contentText = "";

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

                if (data.type === "end") {
                    // Stream complete — send final accumulated text
                    onFinal(buildFullText());
                    onEnd();
                    return;
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
            onEnd();
        });

        sse.stream();

        return () => {
            sse.close();
            sseRef.current = null;
        };
    }, [submission]);

    /** Abort the current SSE stream */
    const abort = () => {
        if (sseRef.current) {
            sseRef.current.close();
            sseRef.current = null;
        }
    };

    return { abort };
}
