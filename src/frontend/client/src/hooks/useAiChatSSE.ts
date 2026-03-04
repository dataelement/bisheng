/**
 * Simplified SSE hook for AI chat streaming.
 * Handles event format:
 *   { created: true, message: {...} }                        → conversation init
 *   { event: "on_run_step", data: {...} }                    → step tracking (ignored)
 *   { event: "on_reasoning_delta", data: { delta: { content: [{ type: "think", think: "..." }] } } }  → thinking delta
 *   { event: "on_message_delta", data: { delta: { content: [{ type: "text", text: "..." }] } } }      → text delta
 *   { final: true, responseMessage: {...}, requestMessage: {...} }  → stream complete
 *
 * Deltas are ACCUMULATED in this hook, and the full text (with :::thinking::: markers)
 * is passed to onMessage on every delta event, enabling real-time streaming display.
 */
import { useEffect, useRef } from "react";
import { SSE } from "sse.js";
import type { ChatMessage, ContentPart } from "~/api/chatApi";
import { getSSEUrl } from "~/api/chatApi";

export interface SSESubmission {
    payload: Record<string, any>;
    userMessage: ChatMessage;
    onCreated: (conversationId: string, userMsg: ChatMessage) => void;
    onMessage: (text: string, messageId: string) => void;
    onFinal: (data: any) => void;
    onError: (error: string) => void;
    onStart: () => void;
    onEnd: () => void;
}

/**
 * Hook that manages SSE connection lifecycle.
 * Accumulates delta text and calls onMessage with full accumulated text.
 */
export default function useAiChatSSE(submission: SSESubmission | null) {
    const sseRef = useRef<any>(null);

    useEffect(() => {
        if (!submission) return;

        const {
            payload,
            userMessage,
            onCreated,
            onMessage,
            onFinal,
            onError,
            onStart,
            onEnd,
        } = submission;

        // Accumulate deltas
        let thinkingText = "";
        let responseText = "";
        let currentMessageId = "";

        const sseUrl = getSSEUrl();

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
                console.log("[SSE] raw event:", data);

                // --- final: stream complete ---
                if (data.final != null) {
                    onFinal(data);
                    onEnd();
                    return;
                }

                // --- created: conversation init ---
                if (data.created != null) {
                    const mergedUser = { ...userMessage, ...data.message };
                    onCreated(
                        data.message?.conversationId || userMessage.conversationId,
                        mergedUser
                    );
                    return;
                }

                // --- event-based delta streaming ---
                if (data.event != null) {
                    const eventType = data.event;

                    // on_run_step → extract messageId for tracking
                    if (eventType === "on_run_step") {
                        const msgId =
                            data.data?.stepDetails?.message_creation?.message_id || "";
                        if (msgId) {
                            currentMessageId = msgId;
                        }
                        return;
                    }

                    // on_reasoning_delta → accumulate thinking text
                    if (eventType === "on_reasoning_delta") {
                        const deltaContent = data.data?.delta?.content;
                        if (deltaContent && Array.isArray(deltaContent)) {
                            for (const part of deltaContent) {
                                if (part.type === "think" && part.think) {
                                    thinkingText += part.think;
                                }
                            }
                        }
                        // Build full text with thinking markers and pass to onMessage
                        const fullText = `:::thinking\n${thinkingText}\n:::`;
                        onMessage(fullText, currentMessageId);
                        return;
                    }

                    // on_message_delta → accumulate response text
                    if (eventType === "on_message_delta") {
                        const deltaContent = data.data?.delta?.content;
                        if (deltaContent && Array.isArray(deltaContent)) {
                            for (const part of deltaContent) {
                                if (part.type === "text" && part.text) {
                                    responseText += part.text;
                                }
                            }
                        }
                        // Build full text: thinking (if any) + response
                        const fullText = thinkingText
                            ? `:::thinking\n${thinkingText}\n:::\n${responseText}`
                            : responseText;
                        onMessage(fullText, currentMessageId);
                        return;
                    }

                    // Unknown event type — log and skip
                    console.log("[SSE] unknown event:", eventType);
                    return;
                }

                // --- fallback: simple text streaming (legacy format) ---
                if (data.text != null || data.response != null || data.message != null) {
                    const text = data.text ?? data.response ?? "";
                    const messageId = data.messageId ?? "";
                    if (text) {
                        onMessage(text, messageId);
                    }
                }
            } catch (err) {
                console.error("[SSE] Failed to parse message:", err);
            }
        });

        sse.addEventListener("error", (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);
                onError(data?.text || data?.message || "Stream error");
            } catch {
                onError("Connection error");
            }
            onEnd();
        });

        sse.addEventListener("cancel", () => {
            onEnd();
        });

        sse.stream();

        return () => {
            const isCancelled = sse.readyState <= 1;
            sse.close();
            if (isCancelled) {
                sse.dispatchEvent(new Event("cancel"));
            }
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
