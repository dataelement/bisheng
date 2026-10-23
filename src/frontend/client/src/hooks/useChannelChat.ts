import { showApiError } from "~/api/request";
/**
 * Channel article chat hook — sends questions in the context of a specific article.
 * Uses the stream-format SSE endpoint (shared with file/folder chat).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useRecoilValue } from "recoil";
import { v4 } from "uuid";
import type { ChatMessage } from "~/api/chatApi";
import {
    getChannelSSEUrl,
    getChannelChatHistory,
    clearChannelChat,
} from "~/api/chatApi";
import useStreamChatSSE, {
    type StreamChatSSESubmission,
} from "~/hooks/useStreamChatSSE";
import store from "~/store";

/**
 * Hook for channel article AI chat.
 * @param articleDocId - ES article document ID; empty string disables the hook.
 */
/**
 * @param model - The surface's own model selection (see useSurfaceModel).
 *   Omitted, it falls back to the shared `chatModel` atom.
 */
export default function useChannelChat(
    articleDocId: string,
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

    const resourceKey = JSON.stringify([articleDocId]);
    const resourceRef = useRef({ key: resourceKey });
    if (resourceRef.current.key !== resourceKey) {
        resourceRef.current = { key: resourceKey };
        clearingRef.current = null;
    }

    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;

    // SSE lifecycle
    const { abort: abortSSE } = useStreamChatSSE(sseSubmission);

    // --- Load chat history on mount or when articleDocId changes ---
    useEffect(() => {
        if (!articleDocId) return;
        let active = true;
        setHistoryError(null);
        setIsClearing(false);
        setIsLoading(true);
        getChannelChatHistory(articleDocId)
            .then(msgs => { if (active) setMessages(msgs); })
            .catch(error => { if (active) setHistoryError(error); })
            .finally(() => { if (active) setIsLoading(false); });
        return () => { active = false; };
    }, [articleDocId, historyReload]);

    // --- Helper: build SSE submission for stream-format ---
    const buildSubmission = useCallback(
        (
            payload: Record<string, any>,
            responseMessageId: string
        ): StreamChatSSESubmission => ({
            sseUrl: getChannelSSEUrl(),
            payload,
            onStart: () => {
                setIsStreaming(true);
            },
            onMessage: (fullText) => {
                setMessages((prev) => {
                    const msgs = [...prev];
                    const idx = msgs.findIndex(
                        (m) => m.messageId === responseMessageId
                    );
                    if (idx >= 0) {
                        msgs[idx] = { ...msgs[idx], text: fullText };
                    }
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
        []
    );

    // --- Send a message ---
    const sendMessage = useCallback(
        (text: string, _files?: any[] | null) => {
            if (clearingRef.current || !text.trim() || isStreaming || !articleDocId) return;

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

            const payload = {
                article_doc_id: articleDocId,
                text: text.trim(),
                model_id: String(chatModel.id || ""),
            };

            // Lock input immediately — don't wait for SSE open event
            setIsStreaming(true);
            setSseSubmission(buildSubmission(payload, responseMessageId));
        },
        [articleDocId, isStreaming, buildSubmission, chatModel.id, chatModel.name]
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
        if (articleDocId) {
            const operation = {};
            clearingRef.current = operation;
            setIsClearing(true);
            const resource = resourceRef.current;
            void clearChannelChat(articleDocId).then(() => {
                if (resourceRef.current === resource) setMessages([]);
            }).catch(showApiError).finally(() => {
                if (clearingRef.current === operation) {
                    clearingRef.current = null;
                    setIsClearing(false);
                }
            });
        }

    }, [stopGenerating, articleDocId]);

    // --- Regenerate (resend last user message) ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (clearingRef.current || isStreaming || !articleDocId) return;

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

            const payload = {
                article_doc_id: articleDocId,
                text: parentMsg.text?.trim() || "",
                model_id: String(chatModel.id || ""),
            };

            setIsStreaming(true);
            setSseSubmission(buildSubmission(payload, newResponseId));
        },
        [articleDocId, isStreaming, buildSubmission, chatModel.id, chatModel.name]
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
