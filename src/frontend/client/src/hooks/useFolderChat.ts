/**
 * Folder/space chat hook — manages sessions, history, and streaming.
 *
 * Flow:
 *  1. Load session list on mount
 *  2. Creating a new session calls the API and gets a chat_id
 *  3. Sending a message uses chat_id + query + optional tags
 *  4. History loads per chat_id
 *  5. Sessions can be switched/deleted
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRecoilValue } from "recoil";
import { v4 } from "uuid";
import type { ChatMessage, FolderSession } from "~/api/chatApi";
import {
    getFolderChatSSEUrl,
    getFolderSessions,
    createFolderSession,
    deleteFolderSession,
    getFolderChatHistory,
    renameConversation,
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
import { closeSupersededRateLimitRecoveries } from "~/hooks/useModelRateLimitRecovery";
import { observeModelRateLimitEvent } from "~/hooks/queries/endpoints/modelRateLimitPolling";

/**
 * Remembers the last active chat id per (space, folder), surviving unmount within
 * the app session. Lets the dock restore the conversation the user was viewing
 * before collapsing (which unmounts/re-inits this hook) instead of blindly
 * re-selecting the most recent session or showing an empty new chat.
 */
const lastActiveChatByKey = new Map<string, string>();
const chatMemoKey = (spaceId: string, folderId?: string) =>
    `${spaceId}::${folderId ?? ""}`;

/** Tag object passed with folder chat messages */
export interface FolderChatTag {
    id: number;
    name: string;
}

/**
 * Hook for folder/space RAG chat.
 * @param spaceId  - Knowledge space ID; empty string disables the hook.
 * @param folderId - Folder ID; undefined means the entire space.
 */
export default function useFolderChat(
    spaceId: string,
    folderId?: string
) {
    const queryClient = useQueryClient();
    const chatModel = useRecoilValue(store.chatModel);
    const [sessions, setSessions] = useState<FolderSession[]>([]);
    const [activeChatId, setActiveChatId] = useState<string>("");
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [isStreaming, setIsStreaming] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [isSessionsLoading, setIsSessionsLoading] = useState(false);
    const [sseSubmission, setSseSubmission] =
        useState<StreamChatSSESubmission | null>(null);

    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;
    const recoveryResolverRef = useRef<((response: ModelRecoveryResponse) => void) | null>(null);
    const recoveryAcceptedRef = useRef(true);
    const recoveryErrorTypeRef = useRef<string | undefined>();

    // Flag to skip history loading when creating a session mid-send
    const skipHistoryLoadRef = useRef(false);

    const enabled = !!spaceId;
    const numericFolderId = folderId ? Number(folderId) : undefined;

    // SSE lifecycle
    const { abort: abortSSE } = useStreamChatSSE(sseSubmission);

    // --- Load session list on mount / when space or folder changes ---
    useEffect(() => {
        if (!enabled) return;
        // Immediately reset state to prevent stale chatId from being used
        // if the user sends a message before the API responds.
        setActiveChatId("");
        setMessages([]);
        setSessions([]);
        setIsSessionsLoading(true);
        getFolderSessions(spaceId, folderId)
            .then((list) => {
                setSessions(list);
                if (list.length > 0) {
                    // Restore the last-viewed session for this space/folder if it still
                    // exists (e.g. after collapsing then re-expanding the dock); otherwise
                    // fall back to the most recent one.
                    const remembered = lastActiveChatByKey.get(chatMemoKey(spaceId, folderId));
                    const restore =
                        remembered && list.some((s) => s.chat_id === remembered)
                            ? remembered
                            : list[0].chat_id;
                    setActiveChatId(restore);
                }
                // list.length === 0 → activeChatId stays "", handled above
            })
            .catch((err) =>
                console.error("[FolderChat] Failed to load sessions:", err)
            )
            .finally(() => setIsSessionsLoading(false));
    }, [spaceId, folderId, enabled]);

    // Remember the active chat per space/folder so a later remount can restore it.
    useEffect(() => {
        if (enabled && activeChatId) {
            lastActiveChatByKey.set(chatMemoKey(spaceId, folderId), activeChatId);
        }
    }, [enabled, spaceId, folderId, activeChatId]);

    // --- Load history when activeChatId changes ---
    useEffect(() => {
        if (!enabled || !activeChatId) {
            setMessages([]);
            return;
        }
        // Skip history load if we just created a session during sendMessage
        if (skipHistoryLoadRef.current) {
            skipHistoryLoadRef.current = false;
            return;
        }
        setIsLoading(true);
        getFolderChatHistory(spaceId, {
            folderId,
            chatId: activeChatId,
        })
            .then((msgs) => setMessages(msgs))
            .catch((err) =>
                console.error("[FolderChat] Failed to load history:", err)
            )
            .finally(() => setIsLoading(false));
    }, [spaceId, folderId, activeChatId, enabled]);

    // --- Helper: build SSE submission ---
    const buildSubmission = useCallback(
        (
            payload: Record<string, any>,
            responseMessageId: string,
            sseUrl = getFolderChatSSEUrl(spaceId),
            recoveryCommand?: ModelRecoveryCommand,
        ): StreamChatSSESubmission => ({
            sseUrl,
            payload,
            onStart: () => setIsStreaming(true),
            onMessage: (fullText) => {
                setMessages((prev) => {
                    const msgs = [...prev];
                    const idx = msgs.findIndex(
                        (m) => m.messageId === responseMessageId
                    );
                    if (
                        idx >= 0
                        && (!recoveryCommand || msgs[idx].attemptId === recoveryCommand.attemptId)
                    ) msgs[idx] = { ...msgs[idx], text: fullText };
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
                recoveryAcceptedRef.current = false;
                recoveryErrorTypeRef.current = meta?.errorType;
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
        [spaceId, queryClient]
    );

    const recoverRateLimitedMessage = useCallback(
        (command: ModelRecoveryCommand): Promise<ModelRecoveryResponse> => {
            const responseMessage = messagesRef.current.find(
                (message) => message.executionId === command.executionId,
            );
            if (!responseMessage || isStreaming || !activeChatId) {
                return Promise.resolve({
                    execution_id: command.executionId,
                    attempt_id: command.attemptId,
                    accepted: false,
                });
            }
            const request = buildModelRecoveryRequest(
                { entry: 'knowledge', spaceId },
                command,
            );
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
        [activeChatId, buildSubmission, isStreaming, spaceId],
    );

    // --- Create a new session ---
    const createSession = useCallback(async () => {
        if (!enabled) return;
        try {
            const session = await createFolderSession(spaceId, numericFolderId);
            setSessions((prev) => [session, ...prev]);
            setActiveChatId(session.chat_id);
            setMessages([]);
            return session;
        } catch (err) {
            console.error("[FolderChat] Failed to create session:", err);
        }
    }, [enabled, spaceId, numericFolderId]);

    // --- Switch to a different session ---
    const switchSession = useCallback(
        (chatId: string) => {
            if (chatId === activeChatId) return;
            // Abort current stream if any
            abortSSE();
            setIsStreaming(false);
            setSseSubmission(null);
            setActiveChatId(chatId);
        },
        [activeChatId, abortSSE]
    );

    // --- Rename a session ---
    const renameSession = useCallback(
        async (chatId: string, name: string) => {
            if (!enabled) return false;
            const trimmed = name.trim();
            if (!trimmed) return false;
            try {
                await renameConversation(chatId, trimmed);
                setSessions((prev) =>
                    prev.map((s) =>
                        s.chat_id === chatId ? { ...s, name: trimmed } : s
                    )
                );
                return true;
            } catch (err) {
                console.error("[FolderChat] Failed to rename session:", err);
                return false;
            }
        },
        [enabled]
    );

    // --- Delete a session ---
    const deleteSession = useCallback(
        async (chatId: string) => {
            if (!enabled) return;
            try {
                await deleteFolderSession(spaceId, chatId, numericFolderId);
                setSessions((prev) => prev.filter((s) => s.chat_id !== chatId));
                // If deleting the active session, switch to the next one or clear
                if (chatId === activeChatId) {
                    setSessions((prev) => {
                        if (prev.length > 0) {
                            setActiveChatId(prev[0].chat_id);
                        } else {
                            setActiveChatId("");
                            setMessages([]);
                        }
                        return prev;
                    });
                }
            } catch (err) {
                console.error("[FolderChat] Failed to delete session:", err);
            }
        },
        [enabled, spaceId, numericFolderId, activeChatId]
    );

    // --- Send a message ---
    const sendMessage = useCallback(
        async (
            text: string,
            _files?: any[] | null,
            tag?: FolderChatTag,
            /** Content ticked in the file list; answers are restricted to it. */
            selectedIds?: string[],
        ) => {
            if (!text.trim() || isStreaming || !enabled) return;

            // If no active session, create one first
            let chatId = activeChatId;
            if (!chatId) {
                // Prevent the history-load effect from overwriting our messages
                skipHistoryLoadRef.current = true;
                const session = await createSession();
                if (!session) {
                    skipHistoryLoadRef.current = false;
                    return;
                }
                chatId = session.chat_id;
            }

            // Encode the optional tag chip into the message text using a
            // `:::tag {...}:::` prefix block. The user bubble parses this back
            // out for rendering, and `parseStreamHistoryItem` rebuilds the
            // same prefix when reloading from history so the chip persists.
            const userMessageId = v4();
            const displayText = tag
                ? `:::tag ${JSON.stringify({ id: tag.id, name: tag.name })}:::\n${text.trim()}`
                : text.trim();
            const userMessage: ChatMessage = {
                text: displayText,
                sender: "User",
                isCreatedByUser: true,
                parentMessageId: "",
                conversationId: chatId,
                messageId: userMessageId,
                error: false,
            };

            const responseMessageId = `${userMessageId}_`;
            const initialResponse: ChatMessage = {
                text: "",
                sender: chatModel.name || "AI",
                isCreatedByUser: false,
                parentMessageId: userMessageId,
                conversationId: chatId,
                messageId: responseMessageId,
                error: false,
            };

            setMessages((prev) => [
                ...closeSupersededRateLimitRecoveries(prev),
                userMessage,
                initialResponse,
            ]);

            // Build payload per API spec. `selected_ids`, when present, replaces
            // folder_id as the answering scope server-side; a tag still only narrows
            // whichever scope is in force.
            const payload: Record<string, any> = {
                folder_id: numericFolderId ?? 0,
                chat_id: chatId,
                query: text.trim(),
                tags: tag ? [{ id: tag.id, name: tag.name }] : [],
                model_id: String(chatModel.id || ""),
                selected_ids: (selectedIds ?? []).map(Number).filter((id) => !Number.isNaN(id)),
            };

            // Lock input immediately — don't wait for SSE open event
            setIsStreaming(true);
            setSseSubmission(buildSubmission(payload, responseMessageId));
        },
        [
            isStreaming,
            enabled,
            activeChatId,
            numericFolderId,
            createSession,
            buildSubmission,
            chatModel.id,
            chatModel.name,
        ]
    );

    // --- Stop generating ---
    const stopGenerating = useCallback(() => {
        abortSSE();
        setIsStreaming(false);
        setSseSubmission(null);
    }, [abortSSE]);

    // --- Clear conversation (delete session + clear local) ---
    const clearConversation = useCallback(() => {
        stopGenerating();
        if (activeChatId && enabled) {
            deleteFolderSession(spaceId, activeChatId, numericFolderId).catch(
                (err) =>
                    console.error(
                        "[FolderChat] Failed to delete session on clear:",
                        err
                    )
            );
            setSessions((prev) =>
                prev.filter((s) => s.chat_id !== activeChatId)
            );
        }
        setActiveChatId("");
        setMessages([]);
    }, [stopGenerating, activeChatId, enabled, spaceId, numericFolderId]);

    // --- Regenerate ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (isStreaming || !enabled || !activeChatId) return;

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
                conversationId: activeChatId,
                messageId: newResponseId,
                error: false,
            };

            setMessages((prev) => [...prev, newResponse]);

            const payload: Record<string, any> = {
                folder_id: numericFolderId ?? 0,
                chat_id: activeChatId,
                query: parentMsg.text?.trim() || "",
                tags: [],
                model_id: String(chatModel.id || ""),
            };

            setSseSubmission(buildSubmission(payload, newResponseId));
        },
        [isStreaming, enabled, activeChatId, numericFolderId, buildSubmission, chatModel.id, chatModel.name]
    );

    return {
        messages,
        sessions,
        activeChatId,
        isLoading,
        isSessionsLoading,
        isStreaming,
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
        createSession,
        switchSession,
        deleteSession,
        renameSession,
        recoverRateLimitedMessage,
    };
}
