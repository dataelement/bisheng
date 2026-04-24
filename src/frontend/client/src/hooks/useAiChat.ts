/**
 * Core chat state hook — manages messages, submission, and SSE lifecycle.
 * Uses useState/useRef for local state, Recoil only for shared atoms (chatModel, kbs, searchType).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRecoilState } from "recoil";
import { v4 } from "uuid";
import type { ConversationData, TConversation } from "~/types/chat";
import { QueryKeys, dataService } from "~/types/chat";
import { addConversation, updateConvoFields } from "~/utils";
import store from "~/store";
import { useLocalize } from "~/hooks";
import type { ChatMessage } from "~/api/chatApi";
import { getAgentMessages } from "~/api/chatApi";
import useAiChatSSE, { type SSESubmission } from "~/hooks/useAiChatSSE";
import { useGetBsConfig } from "~/hooks/queries/data-provider";

const NO_PARENT = "00000000-0000-0000-0000-000000000000";

export default function useAiChat(initialConversationId: string = "new", isLingsi: boolean = false, shareToken: string = "") {
    const localize = useLocalize();
    // --- Local state ---
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [conversationId, setConversationId] = useState(initialConversationId);
    const [title, setTitle] = useState("");
    const [isStreaming, setIsStreaming] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [sseSubmission, setSseSubmission] = useState<SSESubmission | null>(
        null
    );

    // Refs for accessing latest state in callbacks
    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;

    // Shared Recoil atoms
    const [chatModel] = useRecoilState(store.chatModel);
    const [selectedOrgKbs] = useRecoilState(store.selectedOrgKbs);
    const [searchType] = useRecoilState(store.searchType);
    // v2.5 Agent-mode: tools toggled on in the chat input bar. Non-empty
    // means the backend dispatcher routes to the LangGraph Agent flow (which
    // emits the new ChatResponse SSE format). Empty array keeps us on the
    // legacy flow so existing tests / old clients aren't disrupted.
    const [selectedAgentTools] = useRecoilState(store.selectedAgentTools);
    // Admin-level KB toggle. When disabled we strip both org-KB and knowledge-
    // space ids from the outbound payload — defensive, in case stale state
    // restored from localStorage still has entries even after the UI menu is
    // hidden by ChatKnowledge.
    const { data: bsConfig } = useGetBsConfig();

    const queryClient = useQueryClient();

    // --- SSE hook ---
    const { abort: abortSSE } = useAiChatSSE(sseSubmission);

    // Track previous external ID to distinguish sidebar navigation from self-navigate
    const prevExternalIdRef = useRef(initialConversationId);
    const internalConvoIdRef = useRef(conversationId);
    internalConvoIdRef.current = conversationId;

    // --- Sync internal state when external conversationId prop changes ---
    // This is essential for sidebar navigation: clicking a different conversation
    // changes initialConversationId. But we must NOT reset when WE navigated
    // from /new to /c/abc123 after creating a conversation (that would wipe messages).
    useEffect(() => {
        const prevId = prevExternalIdRef.current;
        prevExternalIdRef.current = initialConversationId;

        // Skip on mount (no change)
        if (prevId === initialConversationId) return;

        // Skip if the new external ID matches our own internal ID — this means
        // it was OUR OWN navigation (e.g., /new → /c/abc123 after SSE created convo).
        // In this case don't reset, messages are still valid.
        if (initialConversationId === internalConvoIdRef.current) return;

        // Genuine sidebar navigation — reset and load new conversation.
        // Set isLoading=true up-front (not false) so the welcome page doesn't
        // briefly flash before the load effect fires on the next tick.
        abortSSE();
        setSseSubmission(null);
        setIsStreaming(false);
        setIsLoading(initialConversationId !== "new");
        setMessages([]);
        setTitle("");
        setConversationId(initialConversationId);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [initialConversationId]);

    // --- Load existing messages when conversationId changes ---
    // Only re-runs when conversationId itself changes — NOT when streaming ends.
    // (isStreaming intentionally excluded from deps: when SSE creates a new convo
    // mid-stream we set the conversationId during streaming; if we re-ran on
    // streaming end we'd refetch and overwrite the just-streamed messages,
    // causing a visible flash on the first reply of a new chat.)
    useEffect(() => {
        if (isStreaming) return;
        if (!conversationId || conversationId === "new") {
            return;
        }
        setIsLoading(true);
        // v2.5: use the native Agent-mode history endpoint.
        // Returns ChatMessage[] with category + structured fields (reasoning,
        // tool_calls, steps, thinking_segments) already expanded; legacy
        // regenerate siblings are pre-collapsed server-side.
        getAgentMessages(conversationId)
            .then((msgs) => {
                setMessages(msgs);
                setIsLoading(false);
            })
            .catch((err) => {
                console.error("Failed to load messages:", err);
                setIsLoading(false);
            });
        // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally exclude isStreaming
    }, [conversationId]);

    // v2.5 Module B: agent flow renders a flat list keyed by category;
    // messagesTree + buildMessageTree were only needed by the legacy
    // SiblingSwitch UI which is no longer shown (ChatView passes flatMode).
    // The (still-used) legacy Messages/* component chain imports
    // buildMessageTree directly from chatApi, so only this local indirection
    // is removed.

    // --- Send a message ---
    const sendMessage = useCallback(
        (text: string, files?: any[] | null) => {
            if (!text.trim() || isStreaming) return;

            const parentMsg = messagesRef.current[messagesRef.current.length - 1];
            const parentMessageId = parentMsg?.messageId ?? NO_PARENT;
            const currentConvoId =
                conversationId === "new" ? null : conversationId;
            // Track whether this send started a new conversation (for genTitle)
            const wasNewConvo = conversationId === "new";

            // Create user message
            const userMessageId = v4();
            const userMessage: ChatMessage = {
                text: text.trim(),
                sender: "User",
                clientTimestamp: new Date().toLocaleString("sv").replace(" ", "T"),
                isCreatedByUser: true,
                parentMessageId,
                conversationId: currentConvoId ?? "",
                messageId: userMessageId,
                error: false,
                files: files ?? [],
            };

            // Create placeholder response
            const responseMessageId = `${userMessageId}_`;
            const initialResponse: ChatMessage = {
                text: "",
                sender: chatModel.name || "AI",
                isCreatedByUser: false,
                parentMessageId: userMessageId,
                conversationId: currentConvoId ?? "",
                messageId: responseMessageId,
                error: false,
            };

            // Add both messages immediately
            const updatedMessages = [...messagesRef.current, userMessage, initialResponse];
            setMessages(updatedMessages);

            // Build SSE payload (same structure as useChatFunctions.ask).
            // Backend expects List[int] for both id fields; atom holds strings
            // so we coerce via Number here.
            // When admin disables knowledgeBase, strip both id lists regardless
            // of local state so nothing leaks to the backend.
            const kbDisabled = (bsConfig as any)?.knowledgeBase?.enabled === false;
            const orgKbs = kbDisabled
                ? []
                : selectedOrgKbs.filter((kb) => kb.type === 'org').map((kb) => Number(kb.id));
            const spaceKbs = kbDisabled
                ? []
                : selectedOrgKbs.filter((kb) => kb.type === 'space').map((kb) => Number(kb.id));
            const payload = {
                text: text.trim(),
                clientTimestamp: new Date().toLocaleString("sv").replace(" ", "T"),
                parentMessageId,
                conversationId: currentConvoId,
                messageId: userMessageId,
                endpoint: "",
                endpointType: "custom",
                model: chatModel.id + "",
                search_enabled: searchType === "netSearch",
                use_knowledge_base: {
                    personal_knowledge_enabled: false,
                    organization_knowledge_ids: orgKbs,
                    knowledge_space_ids: spaceKbs,
                },
                isContinued: false,
                isTemporary: false,
                files: files ?? [],
                // v2.5: present `tools` array → backend agent flow.
                // Absent (null/undefined) → legacy flow. We always send the
                // field when the user has toggled any tool on.
                tools: selectedAgentTools.flatMap((g) =>
                    (g.children || []).map((c) => ({
                        id: c.id,
                        tool_key: c.tool_key,
                        type: "tool",
                    })),
                ),
                linsight: isLingsi,
            };

            // Create SSE submission
            const submission: SSESubmission = {
                payload,
                userMessage,
                onStart: () => {
                    console.log('[AiChat] SSE stream started');
                    setIsStreaming(true);
                },
                onCreated: (newConvoId, mergedUser) => {
                    console.log('[AiChat] created:', newConvoId, mergedUser);
                    // Only update conversationId if we got a valid value
                    if (newConvoId && newConvoId !== "") {
                        setConversationId(newConvoId);

                        // Only add placeholder for brand-new conversations to avoid
                        // overwriting an existing conversation's generated title.
                        if (wasNewConvo) {
                            const placeholderConvo = {
                                conversationId: newConvoId,
                                title: localize('com_ui_new_chat'),
                                createdAt: new Date().toISOString(),
                                updatedAt: new Date().toISOString(),
                                model: chatModel.name || '',
                                endpoint: '',
                                endpointType: 'custom',
                                isArchived: false,
                                tags: [],
                            } as unknown as TConversation;

                            queryClient.setQueryData<ConversationData>(
                                [QueryKeys.allConversations],
                                (convoData) => {
                                    if (!convoData) return convoData;
                                    return addConversation(convoData, placeholderConvo);
                                }
                            );
                        }
                    }
                    // Update user message with server-assigned data
                    setMessages((prev) =>
                        prev.map((m) =>
                            m.messageId === userMessageId
                                ? { ...m, ...mergedUser, messageId: userMessageId }
                                : m
                        )
                    );
                },
                onMessage: (text, messageId) => {
                    console.log('[AiChat] message:', { text: text?.slice(0, 50), messageId });
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
                // v2.5 Agent native update — merges structured fields so the
                // AgentMessageBubble can render thinking / tool-calls / answer
                // as separate sections instead of regex-parsing a `:::thinking:::`
                // envelope.
                onAgentUpdate: (patch) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const lastMsg = msgs[msgs.length - 1];
                        if (!lastMsg || lastMsg.isCreatedByUser) return prev;
                        msgs[msgs.length - 1] = {
                            ...lastMsg,
                            // Tag with agent category so the bubble switches to
                            // native rendering. First SSE event upgrades the row;
                            // subsequent ones just refresh fields.
                            category: patch.category ?? lastMsg.category ?? "agent_answer",
                            ...(patch.messageId ? { messageId: patch.messageId } : {}),
                            ...(patch.text != null ? { text: patch.text } : {}),
                            ...(patch.events ? { events: patch.events } : {}),
                            ...(patch.finalised ? { unfinished: false } : {}),
                        };
                        return msgs;
                    });
                },

                onFinal: (data) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        // Update with final response data if available
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
                            // Update user message with final server data
                            const userIdx = msgs.findIndex(
                                (m) => m.messageId === userMessageId
                            );
                            if (userIdx >= 0 && data.requestMessage) {
                                msgs[userIdx] = { ...msgs[userIdx], ...data.requestMessage };
                            }
                        }
                        return msgs;
                    });
                    if (data.conversation?.conversationId) {
                        setConversationId(data.conversation.conversationId);
                    }
                    // If this was a new conversation, call gen_title to get AI-generated title
                    const finalConvoId = data.conversation?.conversationId || internalConvoIdRef.current;
                    if (wasNewConvo && finalConvoId && finalConvoId !== 'new') {
                        dataService.genTitle({ conversationId: finalConvoId })
                            .then((res: { title?: string }) => {
                                if (!res?.title) return;
                                setTitle(res.title);
                                queryClient.setQueryData<ConversationData>(
                                    [QueryKeys.allConversations],
                                    (convoData) => {
                                        if (!convoData) return convoData;
                                        return updateConvoFields(convoData, {
                                            conversationId: finalConvoId,
                                            title: res.title,
                                        } as TConversation);
                                    }
                                );
                            })
                            .catch(() => {
                                // genTitle failure is non-critical — keep 'New Chat' title
                            });
                    } else {
                        // For existing conversations, hot-update title if returned in SSE final
                        const sseTitle = data.conversation?.title || data.conversation?.flow_name;
                        if (sseTitle && finalConvoId && finalConvoId !== 'new') {
                            setTitle(sseTitle);
                            queryClient.setQueryData<ConversationData>(
                                [QueryKeys.allConversations],
                                (convoData) => {
                                    if (!convoData) return convoData;
                                    return updateConvoFields(convoData, {
                                        conversationId: finalConvoId,
                                        title: sseTitle,
                                    } as TConversation);
                                }
                            );
                        }
                    }
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

            // Lock input immediately — don't wait for SSE open event
            setIsStreaming(true);
            setSseSubmission(submission);
        },
        [conversationId, isStreaming, chatModel, selectedOrgKbs, searchType, selectedAgentTools, isLingsi]
    );

    // --- Stop generating ---
    const stopGenerating = useCallback(() => {
        abortSSE();
        setIsStreaming(false);
        setSseSubmission(null);
    }, [abortSSE]);

    // --- Clear conversation ---
    const clearConversation = useCallback(() => {
        stopGenerating();
        setMessages([]);
        setConversationId("new");
        setTitle("");
    }, [stopGenerating]);

    // --- Regenerate: add a new sibling response under the same parent ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (isStreaming) return;

            // Find the parent (user) message
            const parentMsg = messagesRef.current.find(
                (m) => m.messageId === parentMessageId
            );
            if (!parentMsg) return;

            // Create a new placeholder response as sibling
            const newResponseId = v4();
            const newResponse: ChatMessage = {
                text: "",
                sender: chatModel.name || "AI",
                isCreatedByUser: false,
                parentMessageId,
                conversationId: conversationId === "new" ? "" : conversationId,
                messageId: newResponseId,
                error: false,
            };

            // Add the new response to messages (as a sibling of existing responses)
            setMessages((prev) => [...prev, newResponse]);

            // Build SSE payload
            const payload = {
                text: parentMsg.text?.trim() || "",
                clientTimestamp: new Date()
                    .toLocaleString("sv")
                    .replace(" ", "T"),
                parentMessageId:
                    parentMsg.parentMessageId || NO_PARENT,
                conversationId:
                    conversationId === "new" ? null : conversationId,
                messageId: parentMsg.messageId,
                endpoint: "",
                endpointType: "custom",
                model: chatModel.id + "",
                search_enabled: searchType === "netSearch",
                use_knowledge_base: {
                    organization_knowledge_ids: (bsConfig as any)?.knowledgeBase?.enabled === false
                        ? []
                        : selectedOrgKbs.filter((kb) => kb.type === 'org').map((kb) => Number(kb.id)),
                    knowledge_space_ids: (bsConfig as any)?.knowledgeBase?.enabled === false
                        ? []
                        : selectedOrgKbs.filter((kb) => kb.type === 'space').map((kb) => Number(kb.id)),
                },
                isContinued: false,
                isRegenerate: true,
                isTemporary: false,
                files: parentMsg.files ?? [],
                tools: selectedAgentTools.flatMap((g) =>
                    (g.children || []).map((c) => ({
                        id: c.id,
                        tool_key: c.tool_key,
                        type: "tool",
                    })),
                ),
                linsight: isLingsi,
            };

            const submission: SSESubmission = {
                payload,
                userMessage: parentMsg,
                onStart: () => {
                    console.log("[AiChat] Regenerate SSE started");
                    setIsStreaming(true);
                },
                onCreated: (newConvoId) => {
                    if (newConvoId && newConvoId !== "") {
                        setConversationId(newConvoId);
                    }
                },
                onMessage: (text, messageId) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const idx = msgs.findIndex(
                            (m) => m.messageId === newResponseId
                        );
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
                onAgentUpdate: (patch) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const idx = msgs.findIndex(
                            (m) => m.messageId === newResponseId,
                        );
                        if (idx < 0) return prev;
                        msgs[idx] = {
                            ...msgs[idx],
                            category:
                                patch.category ?? msgs[idx].category ?? "agent_answer",
                            ...(patch.messageId ? { messageId: patch.messageId } : {}),
                            ...(patch.text != null ? { text: patch.text } : {}),
                            ...(patch.events ? { events: patch.events } : {}),
                            ...(patch.finalised ? { unfinished: false } : {}),
                        };
                        return msgs;
                    });
                },

                onFinal: (data) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const idx = msgs.findIndex(
                            (m) => m.messageId === newResponseId
                        );
                        if (idx >= 0 && data.responseMessage) {
                            msgs[idx] = { ...msgs[idx], ...data.responseMessage };
                        }
                        return msgs;
                    });
                    if (data.conversation?.conversationId) {
                        setConversationId(data.conversation.conversationId);
                    }
                },
                onError: (error) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const idx = msgs.findIndex(
                            (m) => m.messageId === newResponseId
                        );
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

            setIsStreaming(true);
            setSseSubmission(submission);
        },
        [conversationId, isStreaming, chatModel, selectedOrgKbs, searchType, selectedAgentTools]
    );

    return {
        // State
        messages,
        // Legacy alias — kept null to maintain the old destructuring shape
        // without shipping tree-building on the hot path.
        messagesTree: null as unknown,
        conversationId,
        title,
        isLoading,
        isStreaming,

        // Actions
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
        setConversationId,
    };
}
