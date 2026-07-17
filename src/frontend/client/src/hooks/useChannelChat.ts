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
export default function useChannelChat(articleDocId: string) {
    const chatModel = useRecoilValue(store.chatModel);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [isStreaming, setIsStreaming] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [sseSubmission, setSseSubmission] =
        useState<StreamChatSSESubmission | null>(null);

    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;

    // SSE lifecycle
    const { abort: abortSSE } = useStreamChatSSE(sseSubmission);

    // --- Load chat history on mount or when articleDocId changes ---
    useEffect(() => {
        if (!articleDocId) return;
        setIsLoading(true);
        getChannelChatHistory(articleDocId)
            .then((msgs) => {
                setMessages(msgs);
            })
            .catch((err) => {
                console.error("[ChannelChat] Failed to load history:", err);
            })
            .finally(() => {
                setIsLoading(false);
            });
    }, [articleDocId]);

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
                        msgs[idx] = { ...msgs[idx], text: fullText, retrying: false };
                    }
                    return msgs;
                });
            },
            onFinal: (fullText) => {
                setMessages((prev) => {
                    const msgs = [...prev];
                    const idx = msgs.findIndex(
                        (m) => m.messageId === responseMessageId
                    );
                    if (idx >= 0) {
                        msgs[idx] = { ...msgs[idx], text: fullText, retrying: false };
                    }
                    return msgs;
                });
            },
            onRetry: (progress) => {
                setMessages((prev) => prev.map((message) =>
                    message.messageId === responseMessageId
                        ? { ...message, text: progress.message, error: false, retrying: true }
                        : message
                ));
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
                            text: error.message,
                            error: true,
                            retrying: false,
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
            if (!text.trim() || isStreaming || !articleDocId) return;

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
            const requestPayload = {
                article_doc_id: articleDocId,
                text: text.trim(),
                model_id: String(chatModel.id || ""),
            };
            const initialResponse: ChatMessage = {
                text: "",
                sender: chatModel.name || "AI",
                isCreatedByUser: false,
                parentMessageId: userMessageId,
                conversationId: "",
                messageId: responseMessageId,
                error: false,
                requestPayload,
            };

            setMessages((prev) => [...prev, userMessage, initialResponse]);

            // Lock input immediately — don't wait for SSE open event
            setIsStreaming(true);
            setSseSubmission(buildSubmission(requestPayload, responseMessageId));
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
        stopGenerating();
        setMessages([]);
        if (articleDocId) {
            clearChannelChat(articleDocId).catch((err) => {
                console.error("[ChannelChat] Failed to clear history:", err);
            });
        }
    }, [stopGenerating, articleDocId]);

    // --- Regenerate (resend last user message) ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (isStreaming || !articleDocId) return;

            const parentMsg = messagesRef.current.find(
                (m) => m.messageId === parentMessageId
            );
            if (!parentMsg) return;

            const failedResponse = [...messagesRef.current].reverse().find(
                (message) => message.parentMessageId === parentMessageId && message.error
            );
            const newResponseId = failedResponse?.messageId || v4();
            const requestPayload = failedResponse?.requestPayload ?? {
                article_doc_id: articleDocId,
                text: parentMsg.text?.trim() || "",
                model_id: String(chatModel.id || ""),
            };
            const newResponse: ChatMessage = {
                text: "",
                sender: chatModel.name || "AI",
                isCreatedByUser: false,
                parentMessageId,
                conversationId: "",
                messageId: newResponseId,
                error: false,
                requestPayload,
            };

            setMessages((prev) => failedResponse
                ? prev.map((message) => message.messageId === newResponseId ? newResponse : message)
                : [...prev, newResponse]
            );

            setIsStreaming(true);
            setSseSubmission(buildSubmission(requestPayload, newResponseId));
        },
        [articleDocId, isStreaming, buildSubmission, chatModel.id, chatModel.name]
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
