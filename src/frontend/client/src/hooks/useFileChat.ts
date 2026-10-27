import { showApiError } from "~/api/request";
/**
 * Knowledge space single-file chat hook.
 * Sends user queries in the context of a specific file within a knowledge space.
 * Uses useStreamChatSSE for streaming (shared with channel/folder chat).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useRecoilValue } from "recoil";
import { v4 } from "uuid";
import type { ChatMessage } from "~/api/chatApi";
import { getFileChatSSEUrl, getFileChatHistory, clearFileChatHistory } from "~/api/chatApi";
import useStreamChatSSE, {
    type StreamChatSSESubmission,
} from "~/hooks/useStreamChatSSE";
import store from "~/store";

/**
 * Hook for single-file Q&A chat in a knowledge space.
 * @param spaceId - Knowledge space ID; empty string disables the hook.
 * @param fileId  - File ID within the space; empty string disables the hook.
 * @param model   - The surface's own model selection (see useSurfaceModel).
 *                  Omitted, it falls back to the shared `chatModel` atom, which
 *                  is what the pre-isolation callers relied on.
 */
export default function useFileChat(
    spaceId: string,
    fileId: string,
    model?: { id: number; name: string },
) {
    const sharedChatModel = useRecoilValue(store.chatModel);
    const chatModel = model ?? sharedChatModel;
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [isStreaming, setIsStreaming] = useState(false);
    const [historyError, setHistoryError] = useState<unknown>(null);
    const [historyReload, setHistoryReload] = useState(0);
    const [isClearing, setIsClearing] = useState(false);
    const clearingRef = useRef<object | null>(null);
    const retryHistory = () => setHistoryReload(value => value + 1);
    const [isLoading, setIsLoading] = useState(false);
    const [sseSubmission, setSseSubmission] =
        useState<StreamChatSSESubmission | null>(null);

    const resourceKey = JSON.stringify([spaceId, fileId]);
    const resourceRef = useRef({ key: resourceKey });
    if (resourceRef.current.key !== resourceKey) {
        resourceRef.current = { key: resourceKey };
        clearingRef.current = null;
    }

    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;

    const enabled = !!spaceId && !!fileId;

    // SSE lifecycle
    const { abort: abortSSE } = useStreamChatSSE(sseSubmission);

    // --- Load chat history on mount or when params change ---
    useEffect(() => {
        if (!enabled) return;
        let active = true;
        setHistoryError(null);
        setIsClearing(false);
        setIsLoading(true);
        getFileChatHistory(spaceId, fileId)
            .then(msgs => { if (active) setMessages(msgs); })
            .catch(error => { if (active) setHistoryError(error); })
            .finally(() => { if (active) setIsLoading(false); });
        return () => { active = false; };
    }, [spaceId, fileId, enabled, historyReload]);

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
            onFinal: (fullText, realMessageId) => {
                setMessages((prev) => {
                    const msgs = [...prev];
                    const idx = msgs.findIndex(
                        (m) => m.messageId === responseMessageId
                    );
                    if (idx >= 0) {
                        // Swap the temporary placeholder id for the real persisted
                        // ChatMessage id so like/dislike targets the right row before a reload.
                        msgs[idx] = {
                            ...msgs[idx],
                            text: fullText,
                            ...(realMessageId != null && { messageId: String(realMessageId) }),
                        };
                    }
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
            if (clearingRef.current || !text.trim() || isStreaming || !enabled) return;

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
                sender: chatModel.name || "AI",
                isCreatedByUser: false,
                parentMessageId: userMessageId,
                conversationId: "",
                messageId: responseMessageId,
                error: false,
            };

            setMessages((prev) => [...prev, userMessage, initialResponse]);
            // Lock input immediately — don't wait for SSE open event
            setIsStreaming(true);
            setSseSubmission(
                buildSubmission(
                    { query: text.trim(), model_id: String(chatModel.id || "") },
                    responseMessageId
                )
            );
        },
        [isStreaming, enabled, buildSubmission, chatModel.id, chatModel.name]
    );

    // --- Stop generating ---
    const stopGenerating = useCallback(() => {
        abortSSE();
        setIsStreaming(false);
        setSseSubmission(null);
    }, [abortSSE]);

    // --- Clear conversation (local + server) ---
    const clearConversation = useCallback(() => {
        if (clearingRef.current) return;
        stopGenerating();
        if (enabled) {
            const operation = {};
            clearingRef.current = operation;
            setIsClearing(true);
            const resource = resourceRef.current;
            void clearFileChatHistory(spaceId, fileId).then(() => {
                if (resourceRef.current === resource) setMessages([]);
            }).catch(showApiError).finally(() => {
                if (clearingRef.current === operation) {
                    clearingRef.current = null;
                    setIsClearing(false);
                }
            });
        }

    }, [stopGenerating, enabled, spaceId, fileId]);

    // --- Regenerate (resend last user message) ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (clearingRef.current || isStreaming || !enabled) return;

            const parentMsg = messagesRef.current.find(
                (m) => m.messageId === parentMessageId
            );
            if (!parentMsg) return;

            const newResponseId = v4();
            const newResponse: ChatMessage = {
                text: "",
                sender: chatModel.name || "AI",
                isCreatedByUser: false,
                parentMessageId,
                conversationId: "",
                messageId: newResponseId,
                error: false,
            };

            setMessages((prev) => [...prev, newResponse]);
            setIsStreaming(true);
            setSseSubmission(
                buildSubmission(
                    {
                        query: parentMsg.text?.trim() || "",
                        model_id: String(chatModel.id || ""),
                    },
                    newResponseId
                )
            );
        },
        [isStreaming, enabled, buildSubmission, chatModel.id, chatModel.name]
    );

    return {
        historyError,
        isClearing,
        retryHistory,
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
