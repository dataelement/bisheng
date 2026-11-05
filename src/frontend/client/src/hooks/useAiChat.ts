/**
 * Core chat state hook — manages messages, submission, and SSE lifecycle.
 * Uses useState/useRef for local state, Recoil only for shared atoms (chatModel, kbs, searchType).
 */
import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useChatBuckets } from "./useChatBuckets";
import { useChatSend } from "./useChatSend";
import { useChatAttachmentPoll } from "./useChatAttachmentPoll";
import { useRecoilState } from "recoil";
import { v4 } from "uuid";
import store from "~/store";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import type { ChatMessage } from "~/api/chatApi";
import { getAgentMessages, getSessionName } from "~/api/chatApi";
import { openChatStream, type SSESubmission } from "~/hooks/useAiChatSSE";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { useLinsightManager } from "~/hooks/useLinsightManager";
import { taskModeSkillsState } from "~/store/linsight";
import { isMediaAttachmentFile, type MediaParsingState } from "~/utils/mediaAttachmentUtils";

/**
 * Turns that are still generating, across every mounted chat surface.
 *
 * A turn belongs to its conversation, not to whatever is on screen. Keeping the
 * handles module-level is what lets the user read another chat — or leave this
 * one — without the answer being cancelled behind them: nothing here is torn
 * down by a component effect.
 *
 * The key carries an owner id as well as the conversation, so the workstation
 * view and the subscription AI dock cannot collide on "new" or close each
 * other's turns when one of them unmounts.
 */
type LiveStream = { convoId: string; close: () => void };
const liveStreams = new Map<string, LiveStream>();
const streamKey = (ownerId: string, conversationId: string) => `${ownerId}::${conversationId}`;

/**
 * Close every live turn for a conversation, whoever opened it.
 *
 * Switching conversations no longer closes anything, so deleting one has to say
 * so explicitly — otherwise the backend goes on generating an answer that has
 * nowhere left to be stored.
 */
export function closeChatStream(conversationId: string): void {
    for (const [key, stream] of [...liveStreams]) {
        if (stream.convoId !== conversationId) continue;
        liveStreams.delete(key);
        stream.close();
    }
}

const NO_PARENT = "00000000-0000-0000-0000-000000000000";

export default function useAiChat(initialConversationId: string = "new", isLingsi: boolean = false, shareToken: string = "") {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const { messages, title, isStreaming, isLoading, isParsingMedia, conversationId, streamingByConvo, setConversationId, setMessagesFor, setTitleFor, setStreamingFor, setLoadingFor, setParsingMediaFor, promoteBucket, setMessages, setTitle, setIsStreaming, setIsLoading, setIsParsingMedia } = useChatBuckets(initialConversationId);
    const ownerIdRef = useRef(v4());

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
    // F035 Track H: skills picked in the daily task-mode input live in the shared
    // 'new' atom (AiChatInput keys the picker there). Threaded onto the task-mode
    // turn's submit payload so the user's explicit selection is what gets loaded.
    const [dailyTaskSkills] = useRecoilState(taskModeSkillsState('new'));
    // Admin-level org-KB toggle. Knowledge spaces remain available even when
    // the org knowledge base feature is disabled, so we only strip org ids.
    const { data: bsConfig } = useGetBsConfig();

    const queryClient = useQueryClient();

    // F035 Track J (TJ-6): task-mode turns reuse the linsight execution machinery
    // (createLinsight seeds the per-SV store, startLinsight kicks off the run, the
    // inline task bubble hosts the WS). The turn stays in THIS daily conversation.
    const { createLinsight, updateLinsight, reconcileLinsightFromServer } = useLinsightManager();

    // --- SSE hook ---
    /**
     * Open a turn and register it under the conversation it belongs to.
     *
     * The returned closer is what `stopGenerating`, deleting a conversation and
     * a real unmount reach for. Nothing else closes a turn — in particular,
     * switching conversations does not.
     */
    const beginStream = useCallback(
        (cid: string, submission: SSESubmission) => {
            const ownerId = ownerIdRef.current;
            const previous = liveStreams.get(streamKey(ownerId, cid));
            previous?.close();
            const handle = openChatStream(submission, localize);
            liveStreams.set(streamKey(ownerId, cid), { convoId: cid, close: handle.close });
        },
        [localize],
    );

    /** Close a turn if one is live for this conversation, and forget it. */
    const endStream = useCallback((cid: string) => {
        const key = streamKey(ownerIdRef.current, cid);
        const stream = liveStreams.get(key);
        if (!stream) return;
        stream.close();
        liveStreams.delete(key);
    }, []);

    /** A turn opened on "new" gets its real id mid-stream; move its registration
     *  across so the closer still reaches it. */
    const promoteStream = useCallback((from: string, to: string) => {
        if (!to || to === from) return;
        const ownerId = ownerIdRef.current;
        const stream = liveStreams.get(streamKey(ownerId, from));
        if (!stream) return;
        stream.convoId = to;
        liveStreams.delete(streamKey(ownerId, from));
        liveStreams.set(streamKey(ownerId, to), stream);
    }, []);

    /** Move a turn, and the view, onto the id the server just gave it.
     *
     *  Everything a turn owns is keyed by the conversation it started in, and
     *  what the caller renders is the bucket of whichever id is current. So the
     *  id can never move on its own: point the view at a fresh id without
     *  carrying the bucket and the pane goes blank on content that is still
     *  there, while the bucket left behind resurfaces the next time someone
     *  opens a new chat. Both happened — this is one call so neither half can
     *  be forgotten again.
     */
    const adoptConversationId = useCallback(
        (turn: { cid: string }, next: string) => {
            if (!next || next === turn.cid) return;
            promoteBucket(turn.cid, next);
            promoteStream(turn.cid, next);
            turn.cid = next;
            setConversationId(next);
        },
        [promoteBucket, promoteStream],
    );

    // Every live turn belongs to the page, not to this component's lifetime —
    // but when the page really does go away, they go with it.
    useEffect(
        () => () => {
            const prefix = `${ownerIdRef.current}::`;
            for (const [key, stream] of [...liveStreams]) {
                if (!key.startsWith(prefix)) continue;
                stream.close();
                liveStreams.delete(key);
            }
        },
        [],
    );

    // F035 Track J (TJ-6): after a task handoff we bind the conversation to the
    // freshly-minted chat_id, which would normally trigger a history refetch.
    // But the bot task row isn't persisted yet (the worker writes it at execution
    // start), so a refetch here returns ONLY the user question and CLOBBERS the
    // optimistic task turn — the panel vanishes ("jumps back to empty daily").
    // This ref tells the load effect to skip exactly that one refetch; the live
    // optimistic message + linsightMapState are authoritative for this turn.
    const skipLoadConvoRef = useRef<string | null>(null);

    // Track previous external ID to distinguish sidebar navigation from self-navigate
    const prevExternalIdRef = useRef(initialConversationId);
    const internalConvoIdRef = useRef(conversationId);
    internalConvoIdRef.current = conversationId;

    // Timer for the post-handoff attachment poll. `generation` fences a request
    // that is already in flight: clearing the timeout alone would still let its
    // `.then` re-arm a new one after we unmounted or switched conversations.
    // One poll per conversation, not one for "the" conversation. It used to be a
    // single timer cancelled on every switch, which was correct only while one
    // chat could be live at a time. With buckets, a poll started in A must keep
    // running while the user reads B and must write back into A — cancelling it
    // on switch would strand A's attachments mid-parse, and letting it write to
    // whatever is on screen would put A's files in B's messages.
    const { cancelIngestPoll, pollFiles } = useChatAttachmentPoll(updateLinsight);

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

        // Genuine sidebar navigation. Nothing of the conversation we are leaving
        // is torn down: its stream keeps generating into its own bucket and its
        // attachment poll keeps running, which is the whole point. We only say
        // the conversation we are arriving at is loading — and only if it has
        // nothing of its own yet, so stepping back into a live turn shows it
        // rather than a spinner over content we already have.
        const arriving = initialConversationId;
        const arrivingIsLive = !!streamingByConvo[arriving] || !!liveStreams.get(streamKey(ownerIdRef.current, arriving));
        setLoadingFor(arriving, arriving !== "new" && !arrivingIsLive);
        // Drop the post-handoff skip guard: it only protects the ONE in-place
        // refetch right after a task handoff. The handoff happens mid-stream, so
        // the load effect's `isStreaming` guard already suppresses that refetch
        // and the skip guard never gets consumed — it lingers set to that convo.
        // Once we genuinely navigate away, it's stale; if left set, returning to
        // that convo would hit the skip branch and load NOTHING (blank page on the
        // first switch-back, only loading on the second). Clearing it here makes
        // the first return load history normally.
        skipLoadConvoRef.current = null;
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
        // F035 Track J: skip the one post-handoff refetch that would clobber the
        // optimistic task turn (see skipLoadConvoRef). Consume the guard so a
        // genuine later navigation back to this convo still reloads normally.
        if (conversationId === skipLoadConvoRef.current) {
            skipLoadConvoRef.current = null;
            setIsLoading(false);
            return;
        }
        setIsLoading(true);
        // v2.5: use the native Agent-mode history endpoint.
        // Returns ChatMessage[] with category + structured fields (reasoning,
        // tool_calls, steps, thinking_segments) already expanded; legacy
        // regenerate siblings are pre-collapsed server-side.
        getAgentMessages(conversationId, shareToken || undefined)
            .then((msgs) => {
                setMessages(msgs);
                setIsLoading(false);
            })
            .catch((err) => {
                console.error("Failed to load messages:", err);
                setIsLoading(false);
            });
        // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally exclude isStreaming
    }, [conversationId, shareToken]);

    // Load the conversation's stored name. The history endpoints return messages
    // only, so opening an existing conversation by URL (deep link or share link)
    // left `title` empty and HeaderTitle fell back to "New Chat" — even though
    // the sidebar list showed the real name.
    //
    // Guarded against clobbering a freshly generated title: skip while streaming
    // (a brand-new conversation's row still says "New Chat" until gen_title
    // lands) and never overwrite a title we already hold.
    useEffect(() => {
        if (isStreaming) return;
        if (!conversationId || conversationId === "new") return;
        let cancelled = false;
        getSessionName(conversationId, shareToken || undefined)
            .then((name) => {
                if (cancelled || !name) return;
                setTitle((prev) => (prev ? prev : name));
            })
            .catch(() => {
                // Non-critical: the header keeps the "New Chat" fallback.
            });
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally exclude isStreaming
    }, [conversationId, shareToken]);

    // v2.5 Module B: agent flow renders a flat list keyed by category;
    // messagesTree + buildMessageTree were only needed by the legacy
    // SiblingSwitch UI which is no longer shown (ChatView passes flatMode).
    // The (still-used) legacy Messages/* component chain imports
    // buildMessageTree directly from chatApi, so only this local indirection
    // is removed.

    // --- Send a message ---
    const finishMediaParsing = useCallback((userMsgId: string) => {
        setIsParsingMedia(false);
        setMessages((prev) => {
            let matched = false;
            const next = prev.map((m) => {
                if (!m.isCreatedByUser || !m.files?.length) return m;
                const hasParsingMedia = m.files.some(
                    (f) => isMediaAttachmentFile(f) && f.parsingState === 'parsing',
                );
                if (!hasParsingMedia) return m;
                const matchesTarget =
                    m.messageId === userMsgId || String(m.messageId) === String(userMsgId);
                if (!matchesTarget) return m;
                matched = true;
                return {
                    ...m,
                    files: m.files.map((f) =>
                        isMediaAttachmentFile(f)
                            ? { ...f, parsingState: 'done' as MediaParsingState }
                            : f,
                    ),
                };
            });
            if (matched) return next;

            for (let i = next.length - 1; i >= 0; i -= 1) {
                const m = next[i];
                if (
                    !m.isCreatedByUser
                    || !m.files?.some((f) => isMediaAttachmentFile(f) && f.parsingState === 'parsing')
                ) {
                    continue;
                }
                next[i] = {
                    ...m,
                    files: m.files!.map((f) =>
                        isMediaAttachmentFile(f)
                            ? { ...f, parsingState: 'done' as MediaParsingState }
                            : f,
                    ),
                };
                break;
            }
            return next;
        });
    }, [setIsParsingMedia, setMessages]);

    const sendMessage = useChatSend({ conversationId, isStreaming, chatModel, selectedOrgKbs, selectedAgentTools, dailyTaskSkills, isLingsi, createLinsight, updateLinsight, reconcileLinsightFromServer, localize, showToast, queryClient, finishMediaParsing, messagesRef, setMessagesFor, setTitleFor, setStreamingFor, setParsingMediaFor, adoptConversationId, internalConvoIdRef, skipLoadConvoRef, beginStream, bsConfig, pollFiles });

    // --- Stop generating ---
    const stopGenerating = useCallback(() => {
        // Only the conversation being read. A turn generating in another one is
        // none of this button's business.
        endStream(conversationId);
        cancelIngestPoll(conversationId);
        setIsStreaming(false);
        setIsParsingMedia(false);
    }, [cancelIngestPoll, conversationId, endStream, setIsParsingMedia, setIsStreaming]);

    // --- Clear conversation ---
    const clearConversation = useCallback(() => {
        stopGenerating();
        setMessages([]);
        setConversationId("new");
        setTitle("");
    }, [setMessages, setTitle, stopGenerating]);

    // --- Regenerate: add a new sibling response under the same parent ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (isStreaming) return;
            // This turn belongs to the conversation it started in, and every
            // write below must land there even if the user walks away mid-answer.
            // Shadowing the viewed-conversation writers with turn-scoped ones is
            // what makes that true for all of the callbacks at once: `turn.cid`
            // is the single place the id lives, so a mid-stream promotion from
            // "new" to a real id carries the whole turn with it.
            const turn = { cid: conversationId };
            const setMessages = (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) =>
                setMessagesFor(turn.cid, updater);
            const setIsStreaming = (value: boolean) => setStreamingFor(turn.cid, value);



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
                use_knowledge_base: {
                    organization_knowledge_ids: (bsConfig as any)?.knowledgeBase?.enabled === false
                        ? []
                        : selectedOrgKbs.filter((kb) => kb.type === 'org').map((kb) => Number(kb.id)),
                    knowledge_space_ids: selectedOrgKbs
                        .filter((kb) => kb.type === 'space')
                        .map((kb) => Number(kb.id)),
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
                        adoptConversationId(turn, newConvoId);
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
                                hasAnswerContent: Boolean(text),
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
                        adoptConversationId(turn, data.conversation.conversationId);
                    }
                },
                // Same as the send path: failure copy goes to `errorText` so a
                // partially-streamed answer survives the error.
                onError: (error, errorCode, meta) => {
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const idx = msgs.findIndex(
                            (m) => m.messageId === newResponseId
                        );
                        if (idx >= 0) {
                            msgs[idx] = {
                                ...msgs[idx],
                                errorText: error || localize("workstation.chat.answer_failed"),
                                error: true,
                                errorCode,
                                ...meta,
                            };
                        }
                        return msgs;
                    });
                },
                onEnd: () => {
                    setIsStreaming(false);
                },
            };

            setIsStreaming(true);
            beginStream(turn.cid, submission);
        },
        [conversationId, isStreaming, chatModel, selectedOrgKbs, searchType, selectedAgentTools, localize]
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
        isParsingMedia,

        // Actions
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
        setConversationId,
    };
}
