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
import { v4 } from "uuid";
import type { ChatMessage, FolderSession } from "~/api/chatApi";
import {
    getFolderChatSSEUrl,
    getFolderSessions,
    createFolderSession,
    deleteFolderSession,
    getFolderChatHistory,
} from "~/api/chatApi";
import useStreamChatSSE, {
    type StreamChatSSESubmission,
} from "~/hooks/useStreamChatSSE";

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
                    setActiveChatId(list[0].chat_id);
                }
                // list.length === 0 → activeChatId stays "", handled above
            })
            .catch((err) =>
                console.error("[FolderChat] Failed to load sessions:", err)
            )
            .finally(() => setIsSessionsLoading(false));
    }, [spaceId, folderId, enabled]);

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
            responseMessageId: string
        ): StreamChatSSESubmission => ({
            sseUrl: getFolderChatSSEUrl(spaceId),
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
        [spaceId]
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
        async (text: string, _files?: any[] | null, tag?: FolderChatTag) => {
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

            const userMessageId = v4();
            const userMessage: ChatMessage = {
                text: text.trim(),
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
                sender: "AI",
                isCreatedByUser: false,
                parentMessageId: userMessageId,
                conversationId: chatId,
                messageId: responseMessageId,
                error: false,
            };

            setMessages((prev) => [...prev, userMessage, initialResponse]);

            // Build payload per API spec
            const payload: Record<string, any> = {
                folder_id: numericFolderId ?? 0,
                chat_id: chatId,
                query: text.trim(),
                tags: tag ? [{ id: tag.id, name: tag.name }] : [],
            };

            setSseSubmission(buildSubmission(payload, responseMessageId));
        },
        [
            isStreaming,
            enabled,
            activeChatId,
            numericFolderId,
            createSession,
            buildSubmission,
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
                sender: "AI",
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
            };

            setSseSubmission(buildSubmission(payload, newResponseId));
        },
        [isStreaming, enabled, activeChatId, numericFolderId, buildSubmission]
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
    };
}
