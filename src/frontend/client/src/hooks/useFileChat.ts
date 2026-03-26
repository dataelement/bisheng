/**
 * Knowledge space single-file chat hook.
 * Sends user queries in the context of a specific file within a knowledge space.
 * Uses useStreamChatSSE for streaming (shared with channel/folder chat).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { v4 } from "uuid";
import type { ChatMessage } from "~/api/chatApi";
import { getFileChatSSEUrl, getFileChatHistory, clearFileChatHistory } from "~/api/chatApi";
import useStreamChatSSE, {
    type StreamChatSSESubmission,
} from "~/hooks/useStreamChatSSE";

/**
 * Hook for single-file Q&A chat in a knowledge space.
 * @param spaceId - Knowledge space ID; empty string disables the hook.
 * @param fileId  - File ID within the space; empty string disables the hook.
 */
export default function useFileChat(spaceId: string, fileId: string) {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [isStreaming, setIsStreaming] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [sseSubmission, setSseSubmission] =
        useState<StreamChatSSESubmission | null>(null);

    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;

    const enabled = !!spaceId && !!fileId;

    // SSE lifecycle
    const { abort: abortSSE } = useStreamChatSSE(sseSubmission);

    // --- Load chat history on mount or when params change ---
    useEffect(() => {
        if (!enabled) return;
        setIsLoading(true);
        getFileChatHistory(spaceId, fileId)
            .then((msgs) => setMessages(msgs))
            .catch((err) =>
                console.error("[FileChat] Failed to load history:", err)
            )
            .finally(() => setIsLoading(false));
    }, [spaceId, fileId, enabled]);

    // --- Helper: build SSE submission ---
    const buildSubmission = useCallback(
        (
            payload: Record<string, any>,
            responseMessageId: string
        ): StreamChatSSESubmission => ({
            sseUrl: getFileChatSSEUrl(spaceId, fileId),
            payload,
            onStart: () => setIsStreaming(true),
            onMessage: (fullText) => {
                setMessages((prev) => {
                    const msgs = [...prev];
                    const idx = msgs.findIndex(
                        (m) => m.messageId === responseMessageId
                    );
                    if (idx >= 0) msgs[idx] = { ...msgs[idx], text: fullText };
                    return msgs;
                });
            },
            onFinal: (fullText) => {
                setMessages((prev) => {
                    const msgs = [...prev];
                    const idx = msgs.findIndex(
                        (m) => m.messageId === responseMessageId
                    );
                    if (idx >= 0) msgs[idx] = { ...msgs[idx], text: fullText };
                    return msgs;
                });
            },
            onError: (error) => {
                setMessages((prev) => {
                    const msgs = [...prev];
                    const idx = msgs.findIndex(
                        (m) => m.messageId === responseMessageId
                    );
                    if (idx >= 0) {
                        msgs[idx] = {
                            ...msgs[idx],
                            text: error || "An error occurred, please try again",
                            error: true,
                        };
                    }
                    return msgs;
                });
            },
            onEnd: () => {
                setIsStreaming(false);
                setSseSubmission(null);
            },
        }),
        [spaceId, fileId]
    );

    // --- Send a message ---
    const sendMessage = useCallback(
        (text: string, _files?: any[] | null) => {
            if (!text.trim() || isStreaming || !enabled) return;

            const userMessageId = v4();
            const userMessage: ChatMessage = {
                text: text.trim(),
                sender: "User",
                isCreatedByUser: true,
                parentMessageId: "",
                conversationId: "",
                messageId: userMessageId,
                error: false,
            };

            const responseMessageId = `${userMessageId}_`;
            const initialResponse: ChatMessage = {
                text: "",
                sender: "AI",
                isCreatedByUser: false,
                parentMessageId: userMessageId,
                conversationId: "",
                messageId: responseMessageId,
                error: false,
            };

            setMessages((prev) => [...prev, userMessage, initialResponse]);
            setSseSubmission(
                buildSubmission({ query: text.trim() }, responseMessageId)
            );
        },
        [isStreaming, enabled, buildSubmission]
    );

    // --- Stop generating ---
    const stopGenerating = useCallback(() => {
        abortSSE();
        setIsStreaming(false);
        setSseSubmission(null);
    }, [abortSSE]);

    // --- Clear conversation (local + server) ---
    const clearConversation = useCallback(() => {
        stopGenerating();
        setMessages([]);
        if (enabled) {
            clearFileChatHistory(spaceId, fileId).catch((err) =>
                console.error("[FileChat] Failed to clear history:", err)
            );
        }
    }, [stopGenerating, enabled, spaceId, fileId]);

    // --- Regenerate (resend last user message) ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (isStreaming || !enabled) return;

            const parentMsg = messagesRef.current.find(
                (m) => m.messageId === parentMessageId
            );
            if (!parentMsg) return;

            const newResponseId = v4();
            const newResponse: ChatMessage = {
                text: "",
                sender: "AI",
                isCreatedByUser: false,
                parentMessageId,
                conversationId: "",
                messageId: newResponseId,
                error: false,
            };

            setMessages((prev) => [...prev, newResponse]);
            setSseSubmission(
                buildSubmission(
                    { query: parentMsg.text?.trim() || "" },
                    newResponseId
                )
            );
        },
        [isStreaming, enabled, buildSubmission]
    );

    return {
        messages,
        conversationId: "",
        title: "",
        isLoading,
        isStreaming,
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
    };
}
