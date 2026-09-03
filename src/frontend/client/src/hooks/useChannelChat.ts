/**
 * Channel article chat hook — sends questions in the context of a specific article.
 * Uses the stream-format SSE endpoint (shared with file/folder chat).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
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
import {
    buildModelRecoveryRequest,
    type ModelRecoveryCommand,
    type ModelRecoveryResponse,
} from "~/api/modelRecovery";
import {
    closeSupersededRateLimitRecoveries,
    isRecoveryRequestAccepted,
} from "~/hooks/useModelRateLimitRecovery";
import { observeModelRateLimitEvent } from "~/hooks/queries/endpoints/modelRateLimitPolling";

/**
 * Hook for channel article AI chat.
 * @param articleDocId - ES article document ID; empty string disables the hook.
 */
export default function useChannelChat(articleDocId: string) {
    const queryClient = useQueryClient();
    const chatModel = useRecoilValue(store.chatModel);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [isStreaming, setIsStreaming] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [sseSubmission, setSseSubmission] =
        useState<StreamChatSSESubmission | null>(null);

    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;
    const recoveryResolverRef = useRef<((response: ModelRecoveryResponse) => void) | null>(null);
    const recoveryAcceptedRef = useRef(true);
    const recoveryErrorTypeRef = useRef<string | undefined>();

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
            responseMessageId: string,
            sseUrl = getChannelSSEUrl(),
            recoveryCommand?: ModelRecoveryCommand,
        ): StreamChatSSESubmission => ({
            sseUrl,
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
                    if (
                        idx >= 0
                        && (!recoveryCommand || msgs[idx].attemptId === recoveryCommand.attemptId)
                    ) {
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
                    if (
                        idx >= 0
                        && (!recoveryCommand || msgs[idx].attemptId === recoveryCommand.attemptId)
                    ) {
                        // Swap the temporary placeholder id for the real persisted
                        // ChatMessage id so like/dislike targets the right row before a reload.
                        msgs[idx] = {
                            ...msgs[idx],
                            text: fullText,
                            ...(realMessageId != null && { messageId: String(realMessageId) }),
                            error: false,
                            unfinished: false,
                            rateLimitState: 'normal',
                        };
                    }
                    return msgs;
                });
            },
            onError: (error, meta) => {
                observeModelRateLimitEvent(queryClient, meta);
                recoveryErrorTypeRef.current = meta?.errorType;
                recoveryAcceptedRef.current = isRecoveryRequestAccepted(recoveryErrorTypeRef.current);
                setMessages((prev) => {
                    const msgs = [...prev];
                    const idx = msgs.findIndex(
                        (m) => m.messageId === responseMessageId
                    );
                    if (
                        idx >= 0
                        && (!recoveryCommand || !meta?.attemptId || meta.attemptId === recoveryCommand.attemptId)
                    ) {
                        msgs[idx] = {
                            ...msgs[idx],
                            errorText: error,
                            error: true,
                            errorType: meta?.errorType,
                            executionId: meta?.executionId ?? recoveryCommand?.executionId,
                            attemptId: meta?.attemptId ?? recoveryCommand?.attemptId,
                            recoverySubjectId: meta?.recoverySubjectId ?? recoveryCommand?.subjectId,
                            modelId: meta?.modelId ?? msgs[idx].modelId,
                            rateLimitState: meta?.rateLimitState,
                            resumeMode: meta?.resumeMode,
                            unfinished: meta?.errorType === 'rate_limit',
                        };
                    }
                    return msgs;
                });
            },
            onEnd: () => {
                setIsStreaming(false);
                setSseSubmission(null);
                if (recoveryCommand && recoveryResolverRef.current) {
                    recoveryResolverRef.current({
                        execution_id: recoveryCommand.executionId,
                        attempt_id: recoveryCommand.attemptId,
                        accepted: recoveryAcceptedRef.current,
                        error_type: recoveryErrorTypeRef.current,
                    });
                    recoveryResolverRef.current = null;
                }
            },
        }),
        [queryClient]
    );

    const recoverRateLimitedMessage = useCallback(
        (command: ModelRecoveryCommand): Promise<ModelRecoveryResponse> => {
            const responseMessage = messagesRef.current.find(
                (message) => message.executionId === command.executionId,
            );
            if (!responseMessage || isStreaming || !articleDocId) {
                return Promise.resolve({
                    execution_id: command.executionId,
                    attempt_id: command.attemptId,
                    accepted: false,
                });
            }
            const request = buildModelRecoveryRequest({ entry: 'channel' }, command);
            const baseUrl = (__APP_ENV__.BASE_URL || '').replace(/\/$/, '');
            recoveryAcceptedRef.current = true;
            recoveryErrorTypeRef.current = undefined;
            setMessages((previous) => previous.map((message) => (
                message.executionId === command.executionId
                    ? {
                        ...message,
                        attemptId: command.attemptId,
                        error: false,
                        errorText: undefined,
                        unfinished: true,
                    }
                    : message
            )));
            setIsStreaming(true);
            setSseSubmission(buildSubmission(
                request.body,
                responseMessage.messageId,
                `${baseUrl}${request.url}`,
                command,
            ));
            return new Promise((resolve) => {
                recoveryResolverRef.current = resolve;
            });
        },
        [articleDocId, buildSubmission, isStreaming],
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
            const initialResponse: ChatMessage = {
                text: "",
                sender: chatModel.name || "AI",
                isCreatedByUser: false,
                parentMessageId: userMessageId,
                conversationId: "",
                messageId: responseMessageId,
                error: false,
            };

            setMessages((prev) => [
                ...closeSupersededRateLimitRecoveries(prev),
                userMessage,
                initialResponse,
            ]);

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
        messages,
        conversationId: "",
        title: "",
        isLoading,
        isStreaming,
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
        recoverRateLimitedMessage,
    };
}
