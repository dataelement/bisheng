/**
 * Channel article chat hook — sends questions in the context of a specific article.
 * Uses the channel SSE endpoint with a simplified payload (article_doc_id + text).
 * Reuses useAiChatSSE for streaming, shares the same ChatMessage type as useAiChat.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { v4 } from "uuid";
import type { ChatMessage } from "~/api/chatApi";
import {
    getChannelSSEUrl,
    getChannelChatHistory,
    clearChannelChat,
} from "~/api/chatApi";
import useAiChatSSE, { type SSESubmission } from "~/hooks/useAiChatSSE";

/**
 * Hook for channel article AI chat.
 * @param articleDocId - ES article document ID; empty string disables the hook.
 */
export default function useChannelChat(articleDocId: string) {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [isStreaming, setIsStreaming] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [sseSubmission, setSseSubmission] = useState<SSESubmission | null>(null);

    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;

    // SSE lifecycle
    const { abort: abortSSE } = useAiChatSSE(sseSubmission);

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

    // --- Send a message ---
    const sendMessage = useCallback(
        (text: string, _files?: any[] | null) => {
            if (!text.trim() || isStreaming || !articleDocId) return;

            // Create user message
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

            // Create placeholder response
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

            // Channel-specific payload — only article_doc_id and text
            const payload = {
                article_doc_id: articleDocId,
                text: text.trim(),
            };

            const submission: SSESubmission = {
                payload,
                userMessage,
                sseUrl: getChannelSSEUrl(),
                onStart: () => {
                    setIsStreaming(true);
                },
                onCreated: (_newConvoId, mergedUser) => {
                    // Update user message with any server-assigned data
                    setMessages((prev) =>
                        prev.map((m) =>
                            m.messageId === userMessageId
                                ? { ...m, ...mergedUser, messageId: userMessageId }
                                : m
                        )
                    );
                },
                onMessage: (text, messageId) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const lastMsg = msgs[msgs.length - 1];
                        if (lastMsg && !lastMsg.isCreatedByUser) {
                            msgs[msgs.length - 1] = {
                                ...lastMsg,
                                text,
                                messageId: messageId || lastMsg.messageId,
                            };
                        }
                        return msgs;
                    });
                },
                onFinal: (data) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        if (data.responseMessage) {
                            const lastMsg = msgs[msgs.length - 1];
                            if (lastMsg && !lastMsg.isCreatedByUser) {
                                msgs[msgs.length - 1] = {
                                    ...lastMsg,
                                    ...data.responseMessage,
                                };
                            }
                        }
                        if (data.requestMessage) {
                            const userIdx = msgs.findIndex(
                                (m) => m.messageId === userMessageId
                            );
                            if (userIdx >= 0) {
                                msgs[userIdx] = { ...msgs[userIdx], ...data.requestMessage };
                            }
                        }
                        return msgs;
                    });
                },
                onError: (error) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const lastMsg = msgs[msgs.length - 1];
                        if (lastMsg && !lastMsg.isCreatedByUser) {
                            msgs[msgs.length - 1] = {
                                ...lastMsg,
                                text: error || "发生错误，请重试",
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
            };

            setSseSubmission(submission);
        },
        [articleDocId, isStreaming]
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
        // Call server-side clear API (fire and forget)
        if (articleDocId) {
            clearChannelChat(articleDocId).catch((err) => {
                console.error("[ChannelChat] Failed to clear history:", err);
            });
        }
    }, [stopGenerating, articleDocId]);

    // --- Regenerate (simplified: resend last user message) ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (isStreaming || !articleDocId) return;

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

            const payload = {
                article_doc_id: articleDocId,
                text: parentMsg.text?.trim() || "",
            };

            const submission: SSESubmission = {
                payload,
                userMessage: parentMsg,
                sseUrl: getChannelSSEUrl(),
                onStart: () => {
                    setIsStreaming(true);
                },
                onCreated: () => {},
                onMessage: (text, messageId) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const idx = msgs.findIndex((m) => m.messageId === newResponseId);
                        if (idx >= 0) {
                            msgs[idx] = {
                                ...msgs[idx],
                                text,
                                messageId: messageId || msgs[idx].messageId,
                            };
                        }
                        return msgs;
                    });
                },
                onFinal: (data) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const idx = msgs.findIndex((m) => m.messageId === newResponseId);
                        if (idx >= 0 && data.responseMessage) {
                            msgs[idx] = { ...msgs[idx], ...data.responseMessage };
                        }
                        return msgs;
                    });
                },
                onError: (error) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const idx = msgs.findIndex((m) => m.messageId === newResponseId);
                        if (idx >= 0) {
                            msgs[idx] = {
                                ...msgs[idx],
                                text: error || "发生错误，请重试",
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
            };

            setSseSubmission(submission);
        },
        [articleDocId, isStreaming]
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

