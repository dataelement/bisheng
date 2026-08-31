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
import { useToastContext } from "~/Providers";
import type { ChatMessage } from "~/api/chatApi";
import { getAgentMessages, getSessionName } from "~/api/chatApi";
import { openChatStream, type ChatStreamHandle, type SSESubmission } from "~/hooks/useAiChatSSE";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { useLinsightManager } from "~/hooks/useLinsightManager";
import { startLinsight, getLinsightSessionVersionList } from "~/api/linsight";
import { SopStatus, taskModeSkillsState } from "~/store/linsight";
import {
    buildModelRecoveryRequest,
    type ModelRecoveryCommand,
    type ModelRecoveryResponse,
} from "~/api/modelRecovery";
import { closeSupersededRateLimitRecoveries } from "~/hooks/useModelRateLimitRecovery";
import { observeModelRateLimitEvent } from "~/hooks/queries/endpoints/modelRateLimitPolling";

const NO_PARENT = "00000000-0000-0000-0000-000000000000";

/** Stable identity, so a conversation with no bucket yet doesn't hand out a
    fresh array on every render and retrigger every downstream memo. */
const EMPTY_MESSAGES: ChatMessage[] = [];

/** One in-flight SSE turn. `convoId` is mutable on purpose: a turn started on
    "new" is re-keyed the moment the backend mints the real conversation id, so
    the stream follows the conversation rather than the screen. `ownerId`
    identifies the hook instance that started it, since more than one chat
    surface mounts this hook (workstation ChatView + the subscription AI dock). */
interface LiveStream {
    convoId: string;
    ownerId: string;
    handle: ChatStreamHandle;
}

/**
 * Live SSE turns. At most one per conversation per surface — `sendMessage`
 * refuses while that conversation streams.
 *
 * Module-level rather than a ref because a turn now outlives the screen it was
 * started on, and code outside this hook (deleting a conversation) has to be
 * able to stop one. Mirrors `wsMap` / `closeAppChatWebSocket` in appChat.
 *
 * Keys are `ownerId::conversationId`, not the bare id: two surfaces can each
 * hold an unsaved conversation keyed "new" at the same time.
 */
const liveStreams = new Map<string, LiveStream>();

const streamKey = (ownerId: string, conversationId: string) => `${ownerId}::${conversationId}`;

/** How many recently-visited conversations keep their messages in memory. */
const RECENT_CONVO_LIMIT = 5;

/**
 * Stop any turn streaming into `conversationId`, whichever surface started it.
 * Call this when the conversation itself goes away — a deleted chat must not
 * leave a generation running on the backend with nowhere to land.
 */
export function closeChatStream(conversationId: string): void {
    for (const [key, stream] of [...liveStreams]) {
        if (stream.convoId !== conversationId) continue;
        liveStreams.delete(key);
        stream.handle.close();
    }
}

/** The fields of an input-box attachment that decide whether it can be sent.
    Backends disagree on the path key (filepath / file_path / file_url), so all
    three count as "the upload landed somewhere we can point at". */
interface OutgoingAttachment {
    filepath?: string;
    file_path?: string;
    file_url?: string;
    valid?: boolean;
    name?: string;
    filename?: string;
    file_name?: string;
}

export default function useAiChat(initialConversationId: string = "new", isLingsi: boolean = false, shareToken: string = "") {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    // --- Local state ---
    // Chat state is bucketed BY CONVERSATION instead of held as one active set.
    // Switching conversations used to wipe it *and* abort the stream, and the
    // backend runs the whole turn inside that stream — so clicking away mid
    // answer killed the generation and you came back to a truncated, error
    // flagged reply. Buckets plus a stream registry let a turn keep streaming
    // into its own conversation while you read another one; switching only
    // changes which bucket is on screen.
    const [messagesByConvo, setMessagesByConvo] = useState<Record<string, ChatMessage[]>>({});
    const [titleByConvo, setTitleByConvo] = useState<Record<string, string>>({});
    const [streamingByConvo, setStreamingByConvo] = useState<Record<string, boolean>>({});
    const [loadingByConvo, setLoadingByConvo] = useState<Record<string, boolean>>({});
    const [conversationId, setConversationId] = useState(initialConversationId);

    // What the caller sees: the active conversation's slice of the above.
    const messages = messagesByConvo[conversationId] ?? EMPTY_MESSAGES;
    const title = titleByConvo[conversationId] ?? "";
    const isStreaming = !!streamingByConvo[conversationId];
    const isLoading = !!loadingByConvo[conversationId];

    // Identifies this hook instance's streams inside the shared registry, so
    // unmounting one chat surface can't tear down another's turns.
    const ownerIdRef = useRef<string>("");
    if (!ownerIdRef.current) ownerIdRef.current = v4();

    /** This instance's view of the shared registry. */
    const keyOf = useCallback((cid: string) => streamKey(ownerIdRef.current, cid), []);
    const streamFor = useCallback((cid: string) => liveStreams.get(streamKey(ownerIdRef.current, cid)), []);
    const hasStreamFor = useCallback((cid: string) => liveStreams.has(streamKey(ownerIdRef.current, cid)), []);

    // --- Bucket writers -------------------------------------------------
    // Every write names the conversation it targets, because a turn's callbacks
    // may well fire while the user is reading a different chat.
    const setBucket = useCallback(
        (cid: string, updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
            setMessagesByConvo((prev) => {
                const cur = prev[cid] ?? EMPTY_MESSAGES;
                const next = typeof updater === "function" ? updater(cur) : updater;
                return next === cur ? prev : { ...prev, [cid]: next };
            });
        },
        [],
    );

    const setTitleFor = useCallback(
        (cid: string, updater: string | ((prev: string) => string)) => {
            setTitleByConvo((prev) => {
                const cur = prev[cid] ?? "";
                const next = typeof updater === "function" ? updater(cur) : updater;
                return next === cur ? prev : { ...prev, [cid]: next };
            });
        },
        [],
    );

    const setStreamingFlag = useCallback((cid: string, value: boolean) => {
        setStreamingByConvo((prev) => (!!prev[cid] === value ? prev : { ...prev, [cid]: value }));
    }, []);

    const setLoadingFlag = useCallback((cid: string, value: boolean) => {
        setLoadingByConvo((prev) => (!!prev[cid] === value ? prev : { ...prev, [cid]: value }));
    }, []);

    /** A turn started on "new" gets its real conversation id mid-stream. Move
     *  its bucket and its registry entry across so the still-open stream keeps
     *  writing into the conversation the user will actually navigate to. */
    const promoteConversation = useCallback((stream: LiveStream, newId: string) => {
        const oldId = stream.convoId;
        if (!newId || newId === oldId) return;
        stream.convoId = newId;
        const ownerId = ownerIdRef.current;
        if (liveStreams.get(streamKey(ownerId, oldId)) === stream) {
            liveStreams.delete(streamKey(ownerId, oldId));
        }
        liveStreams.set(streamKey(ownerId, newId), stream);
        const rekey = <T,>(prev: Record<string, T>): Record<string, T> => {
            if (!(oldId in prev)) return prev;
            const { [oldId]: moved, ...rest } = prev;
            return { ...rest, [newId]: moved };
        };
        setMessagesByConvo(rekey);
        setTitleByConvo(rekey);
        setStreamingByConvo(rekey);
        setLoadingByConvo(rekey);
    }, []);

    // Refs for accessing latest state in callbacks
    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;
    // Lets the load effects ask "do we already have something to render for
    // this conversation?" without taking the whole map as a dependency.
    const messagesByConvoRef = useRef(messagesByConvo);
    messagesByConvoRef.current = messagesByConvo;

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
    const { createLinsight, updateLinsight } = useLinsightManager();

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

        // Genuine sidebar navigation. Nothing is torn down: a turn still
        // streaming keeps its connection and keeps writing into its OWN bucket,
        // which is the whole point — leaving a conversation must not cancel the
        // answer being generated in it. We only move which bucket is on screen.
        // Mark the target as loading up-front (not false) so the welcome page
        // doesn't briefly flash before the load effect fires on the next tick.
        if (
            initialConversationId !== "new" &&
            !hasStreamFor(initialConversationId) &&
            !messagesByConvoRef.current[initialConversationId]
        ) {
            setLoadingFlag(initialConversationId, true);
        }
        // Drop the post-handoff skip guard: it only protects the ONE in-place
        // refetch right after a task handoff. The handoff happens mid-stream, so
        // the load effect's live-stream guard already suppresses that refetch
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
    // The server is authoritative for any conversation that is NOT streaming,
    // so returning to an idle chat always refetches. A conversation with a live
    // stream is the exception: its bucket holds a turn that is still being
    // written and is ahead of anything persisted, so refetching would clobber
    // the reply mid-flight. That registry check also covers the mid-stream
    // new → real id promotion, which lands us here while the turn is running.
    useEffect(() => {
        if (!conversationId || conversationId === "new") {
            return;
        }
        if (hasStreamFor(conversationId)) {
            setLoadingFlag(conversationId, false);
            return;
        }
        // F035 Track J: skip the one post-handoff refetch that would clobber the
        // optimistic task turn (see skipLoadConvoRef). Consume the guard so a
        // genuine later navigation back to this convo still reloads normally.
        if (conversationId === skipLoadConvoRef.current) {
            skipLoadConvoRef.current = null;
            setLoadingFlag(conversationId, false);
            return;
        }
        const cid = conversationId;
        // Only show the loading state when there is nothing to render yet. A
        // conversation still in the recent-bucket cache refetches silently
        // underneath the messages already on screen, so stepping back into it
        // feels instant instead of flashing a spinner over content we have.
        setLoadingFlag(cid, !messagesByConvoRef.current[cid]);
        // v2.5: use the native Agent-mode history endpoint.
        // Returns ChatMessage[] with category + structured fields (reasoning,
        // tool_calls, steps, thinking_segments) already expanded; legacy
        // regenerate siblings are pre-collapsed server-side.
        getAgentMessages(cid, shareToken || undefined)
            .then((msgs) => {
                setBucket(cid, msgs);
                setLoadingFlag(cid, false);
            })
            .catch((err) => {
                console.error("Failed to load messages:", err);
                setLoadingFlag(cid, false);
            });
    }, [conversationId, shareToken, hasStreamFor, setBucket, setLoadingFlag]);

    // Load the conversation's stored name. The history endpoints return messages
    // only, so opening an existing conversation by URL (deep link or share link)
    // left `title` empty and HeaderTitle fell back to "New Chat" — even though
    // the sidebar list showed the real name.
    //
    // Guarded against clobbering a freshly generated title: skip while streaming
    // (a brand-new conversation's row still says "New Chat" until gen_title
    // lands) and never overwrite a title we already hold.
    useEffect(() => {
        if (!conversationId || conversationId === "new") return;
        if (hasStreamFor(conversationId)) return;
        const cid = conversationId;
        let cancelled = false;
        getSessionName(cid, shareToken || undefined)
            .then((name) => {
                if (cancelled || !name) return;
                setTitleFor(cid, (prev) => (prev ? prev : name));
            })
            .catch(() => {
                // Non-critical: the header keeps the "New Chat" fallback.
            });
        return () => {
            cancelled = true;
        };
    }, [conversationId, shareToken, hasStreamFor, setTitleFor]);

    // Bucket retention: what's on screen, anything still streaming, and the last
    // few conversations visited so switching back is instant. Everything else is
    // dropped — the server is authoritative for an idle conversation, so holding
    // every one ever opened would just grow without bound over a long session.
    const recentConvosRef = useRef<string[]>([]);
    useEffect(() => {
        const recent = [
            conversationId,
            ...recentConvosRef.current.filter((id) => id !== conversationId),
        ].slice(0, RECENT_CONVO_LIMIT);
        recentConvosRef.current = recent;
        const keep = new Set<string>(recent);
        for (const stream of liveStreams.values()) {
            if (stream.ownerId === ownerIdRef.current) keep.add(stream.convoId);
        }
        const prune = <T,>(prev: Record<string, T>): Record<string, T> => {
            const next: Record<string, T> = {};
            let dropped = false;
            for (const key of Object.keys(prev)) {
                if (keep.has(key)) next[key] = prev[key];
                else dropped = true;
            }
            return dropped ? next : prev;
        };
        setMessagesByConvo(prune);
        setTitleByConvo(prune);
        setStreamingByConvo(prune);
        setLoadingByConvo(prune);
    }, [conversationId]);

    // Close this instance's live streams when the hook goes away for good.
    // Conversation switching no longer comes through here — only a real
    // unmount does — and we touch only our own turns, never another surface's.
    useEffect(() => {
        const ownerId = ownerIdRef.current;
        return () => {
            for (const [key, stream] of [...liveStreams]) {
                if (stream.ownerId !== ownerId) continue;
                liveStreams.delete(key);
                stream.handle.close();
            }
        };
    }, []);

    // v2.5 Module B: agent flow renders a flat list keyed by category;
    // messagesTree + buildMessageTree were only needed by the legacy
    // SiblingSwitch UI which is no longer shown (ChatView passes flatMode).
    // The (still-used) legacy Messages/* component chain imports
    // buildMessageTree directly from chatApi, so only this local indirection
    // is removed.

    // --- Send a message ---
    const sendMessage = useCallback(
        (text: string, files?: any[] | null, opts?: { taskMode?: boolean }) => {
            if (!text.trim() || isStreaming) return;
            const taskMode = !!opts?.taskMode;

            // An attachment whose upload never landed carries no storage path. It
            // used to be sent anyway: the backend stored it as an attachment with
            // no object name, the model never saw it, and on render the bubble
            // showed "图片已失效" — so the user got an answer that quietly ignored
            // one of their files. Block the send and name the offender instead.
            const stranded = ((files ?? []) as OutgoingAttachment[]).filter(
                (f) => f && (f.valid === false || !(f.filepath || f.file_path || f.file_url)),
            );
            if (stranded.length) {
                showToast({
                    message: localize("com_error_file_upload_incomplete", {
                        0: stranded.map((f) => f.name || f.filename || f.file_name || "").join("、"),
                    }),
                    status: "error",
                });
                return;
            }

            // Drop client-only fields (e.g. the local `previewUrl` blob string used
            // for input-box image previews) before they reach the message state or
            // the SSE payload — the backend only cares about the file ids/paths.
            const cleanFiles = (files ?? []).map(({ previewUrl, ...rest }) => rest);

            const parentMsg = messagesRef.current[messagesRef.current.length - 1];
            const parentMessageId = parentMsg?.messageId ?? NO_PARENT;
            const currentConvoId =
                conversationId === "new" ? null : conversationId;
            // Track whether this send started a new conversation (for genTitle)
            const wasNewConvo = conversationId === "new";

            // This turn belongs to a CONVERSATION, not to whatever is on screen.
            // Everything below writes through `stream.convoId`, which follows the
            // conversation across the new → real id promotion, so the user can
            // walk away mid-answer and the tokens still land in the right chat.
            const stream: LiveStream = {
                convoId: conversationId,
                ownerId: ownerIdRef.current,
                // Replaced by the real handle once the stream opens; a no-op
                // keeps `stopGenerating` / unmount safe in the window before.
                handle: { close: () => { /* not open yet */ } },
            };
            const setMessages = (
                updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[]),
            ) => setBucket(stream.convoId, updater);
            const setIsStreaming = (value: boolean) => setStreamingFlag(stream.convoId, value);
            const setTitle = (value: string) => setTitleFor(stream.convoId, value);

            /** Bind this turn to the conversation id the backend just minted.
                Moves the bucket, then pulls the VIEW along only if the user is
                still watching this turn — yanking someone out of the chat they
                deliberately switched to would be worse than the bug this fixes. */
            const bindConversation = (newId: string) => {
                if (!newId || newId === stream.convoId) return;
                const viewingThisTurn = internalConvoIdRef.current === stream.convoId;
                promoteConversation(stream, newId);
                if (viewingThisTurn) setConversationId(newId);
            };

            /** Drop this turn from the registry once it is over, so returning to
                the conversation refetches the persisted version. */
            const deregister = () => {
                if (streamFor(stream.convoId) === stream) {
                    liveStreams.delete(keyOf(stream.convoId));
                }
            };

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
                files: cleanFiles,
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
            const updatedMessages = [
                ...closeSupersededRateLimitRecoveries(messagesRef.current),
                userMessage,
                initialResponse,
            ];
            setMessages(updatedMessages);

            // Build SSE payload (same structure as useChatFunctions.ask).
            // Backend expects List[int] for both id fields; atom holds strings
            // so we coerce via Number here.
            const orgKbDisabled = (bsConfig as any)?.knowledgeBase?.enabled === false;
            const orgKbs = orgKbDisabled
                ? []
                : selectedOrgKbs.filter((kb) => kb.type === 'org').map((kb) => Number(kb.id));
            const spaceKbs = selectedOrgKbs
                .filter((kb) => kb.type === 'space')
                .map((kb) => Number(kb.id));
            const payload = {
                text: text.trim(),
                clientTimestamp: new Date().toLocaleString("sv").replace(" ", "T"),
                parentMessageId,
                conversationId: currentConvoId,
                messageId: userMessageId,
                endpoint: "",
                endpointType: "custom",
                model: chatModel.id + "",
                use_knowledge_base: {
                    personal_knowledge_enabled: false,
                    organization_knowledge_ids: orgKbs,
                    knowledge_space_ids: spaceKbs,
                },
                isContinued: false,
                isTemporary: false,
                files: cleanFiles,
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
                // F035 Track J (TJ-6): route this turn to the linsight task kernel
                // via the SAME unified entry. Backend replies with a handoff event.
                task_mode: taskMode,
                // F035 Track H: send the picked skill names on task-mode turns so
                // the backend materializes exactly those (empty = none). Omitted
                // outside task mode (the daily chain ignores it).
                skills: taskMode ? dailyTaskSkills.map((s) => s.name) : [],
            };

            // Correlation key for the user (question) message. Starts as the
            // client-side temp UUID, then gets promoted to the real persisted
            // DB id once the backend's `created` event delivers it (see
            // onCreated). Kept in sync so later callbacks (onFinal) and the
            // F028 export selection address the question by its real id rather
            // than a temp value the backend never persisted.
            let realUserMessageId = userMessageId;

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
                        bindConversation(newConvoId);

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
                    // Promote the question message to its real persisted DB id.
                    // The `created` event carries the backend message_id in
                    // mergedUser.messageId; older code pinned it back to the
                    // temp UUID here, which left the question unexportable
                    // (F028 parses messageId as an int — a UUID becomes NaN and
                    // the whole question turn is silently dropped from exports).
                    const serverMessageId =
                        mergedUser.messageId != null && mergedUser.messageId !== ""
                            ? String(mergedUser.messageId)
                            : userMessageId;
                    realUserMessageId = serverMessageId;
                    setMessages((prev) =>
                        prev.map((m) =>
                            m.messageId === userMessageId
                                ? { ...m, ...mergedUser, messageId: serverMessageId }
                                : m
                        )
                    );
                },
                // F035 Track J (TJ-6): task-mode handoff. Promote the placeholder
                // assistant turn into a `task` row pointing at the linsight SV,
                // seed the per-SV store, and kick off execution. The inline task
                // bubble (TJ-7) hosts the WS and renders the live run from there.
                onTaskHandoff: ({ session_version_id: svid, chat_id }) => {
                    if (!svid) return;

                    // The handoff is the daily SSE's last act: the task now runs via
                    // the linsight worker/WS, so the daily stream is done. Clear
                    // isStreaming NOW instead of waiting for the stream to drop on
                    // its own (which can lag) — otherwise the input's stop button,
                    // gated on `isStreaming || taskRunning`, stays lit after a task
                    // is terminated (incl. from the QueueCard) until the stale stream
                    // finally closes. With this, taskRunning alone drives the button,
                    // so every terminate path syncs the input immediately. (QA: stop
                    // /cancel while queued.)
                    setIsStreaming(false);

                    // Bind this conversation (new convo: chat_id was just minted
                    // server-side as a flow_type=15 daily session). Guard the load
                    // effect from refetching (and clobbering) the optimistic task
                    // turn before the worker has persisted the bot task row.
                    if (chat_id) {
                        skipLoadConvoRef.current = chat_id;
                        bindConversation(chat_id);
                        if (wasNewConvo) {
                            const placeholderConvo = {
                                conversationId: chat_id,
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
                                (convoData) =>
                                    convoData ? addConversation(convoData, placeholderConvo) : convoData,
                            );
                        }
                    }

                    // Seed the linsight execution store for this SV, then start it.
                    createLinsight(svid, {
                        status: SopStatus.SopGenerating,
                        question: text.trim(),
                        tasks: [],
                        sessionSteps: [],
                        history: [],
                        output_result: null,
                        file_list: [],
                        files: [],
                        tools: [],
                        session_id: chat_id,
                        version: svid,
                        queueCount: 0,
                        taskError: '',
                        sopError: '',
                        inputSop: false,
                    } as any);

                    startLinsight(svid)
                        .then(() => updateLinsight(svid, { status: SopStatus.Running }))
                        .catch((err) => {
                            console.error('[AiChat] task start-execute failed:', err);
                            updateLinsight(svid, { taskError: String(err), status: SopStatus.Stoped });
                        });

                    // The handoff event carries no files; the backend has already
                    // processed the uploaded sources for this SV. Pull them so the
                    // workspace drawer (uploaded-files group + header button) shows
                    // live instead of only after a page refresh.
                    if (chat_id) {
                        getLinsightSessionVersionList(chat_id, '')
                            .then((versions: any[]) => {
                                const item = (versions || []).find((v: any) => v.id === svid);
                                if (item?.files?.length) {
                                    updateLinsight(svid, {
                                        files: item.files.map((f: any) => ({
                                            ...f,
                                            file_name: decodeURIComponent(f.original_filename),
                                        })),
                                    } as any);

                                    // Stamp the user question's attachment chips with each
                                    // file's parse result so a failed attachment shows its
                                    // failed state live (not only after a refresh).
                                    const statusById = new Map<string, any>(
                                        item.files
                                            .filter((f: any) => f?.file_id != null)
                                            .map((f: any) => [String(f.file_id), f]),
                                    );
                                    setMessages((prev) =>
                                        prev.map((m) =>
                                            m.messageId === realUserMessageId && m.files?.length
                                                ? {
                                                      ...m,
                                                      files: m.files.map((mf: any) => {
                                                          const p = statusById.get(String(mf.file_id));
                                                          return p
                                                              ? {
                                                                    ...mf,
                                                                    valid: p.valid,
                                                                    parsing_status: p.parsing_status,
                                                                    error_message: p.error_message,
                                                                }
                                                              : mf;
                                                      }),
                                                  }
                                                : m,
                                        ),
                                    );
                                }
                            })
                            .catch(() => {
                                /* best-effort: drawer still works after refresh */
                            });
                    }

                    // Promote the placeholder assistant row to a task turn so the
                    // bubble renders the embedded execution panel by SV.
                    setMessages((prev) => {
                        return prev.map((m) =>
                            m.messageId === responseMessageId
                                ? {
                                      ...m,
                                      category: 'task',
                                      linsightSessionVersionId: svid,
                                      conversationId: chat_id || m.conversationId,
                                      unfinished: true,
                                  }
                                : m,
                        );
                    });

                    // New task conversations have no daily `final` event to drive
                    // title generation — request it explicitly. The gen_title
                    // endpoint waits until the backend has persisted a real name,
                    // so this no longer races slow models.
                    if (wasNewConvo && chat_id) {
                        dataService.genTitle({ conversationId: chat_id })
                            .then((res: { title?: string }) => {
                                if (!res?.title) return;
                                setTitle(res.title);
                                queryClient.setQueryData<ConversationData>(
                                    [QueryKeys.allConversations],
                                    (convoData) =>
                                        convoData
                                            ? updateConvoFields(convoData, {
                                                  conversationId: chat_id,
                                                  title: res.title,
                                              } as TConversation)
                                            : convoData,
                                );
                            })
                            .catch(() => { /* non-critical */ });
                    }
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
                            // Match by the (possibly promoted) real id first,
                            // falling back to the temp UUID for the window
                            // before `created` landed. onCreated may already
                            // have swapped the question's messageId to the real
                            // DB id, so a plain userMessageId lookup would miss.
                            const userIdx = msgs.findIndex(
                                (m) =>
                                    m.messageId === realUserMessageId ||
                                    m.messageId === userMessageId
                            );
                            if (userIdx >= 0 && data.requestMessage) {
                                msgs[userIdx] = { ...msgs[userIdx], ...data.requestMessage };
                            }
                        }
                        return msgs;
                    });
                    if (data.conversation?.conversationId) {
                        bindConversation(data.conversation.conversationId);
                    }
                    // New conversation: fetch the AI-generated title. The gen_title
                    // endpoint waits until the backend's background task persists a
                    // real name, so this no longer races slow models (>5s).
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
                // The failure copy lands in `errorText`, never in `text`: the backend
                // emits the SSE error event *before* it finishes the turn, so a stream
                // that already produced an answer would lose it if we overwrote `text`
                // (and the bubble would then render that answer as raw error text).
                onError: (error, errorCode, meta) => {
                    observeModelRateLimitEvent(queryClient, meta);
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const lastMsg = msgs[msgs.length - 1];
                        if (lastMsg && !lastMsg.isCreatedByUser) {
                            msgs[msgs.length - 1] = {
                                ...lastMsg,
                                errorText: error || localize("workstation.chat.answer_failed"),
                                error: true,
                                errorCode,
                                errorType: meta?.errorType,
                                errorDetail: meta?.errorDetail,
                                executionId: meta?.executionId,
                                attemptId: meta?.attemptId,
                                recoverySubjectId: meta?.recoverySubjectId,
                                modelId: meta?.modelId,
                                rateLimitState: meta?.rateLimitState,
                                resumeMode: meta?.resumeMode,
                                unfinished: meta?.errorType === "rate_limit",
                            };
                        }
                        return msgs;
                    });
                },
                onEnd: () => {
                    setIsStreaming(false);
                    deregister();
                },
            };

            // Lock input immediately — don't wait for SSE open event
            setIsStreaming(true);
            liveStreams.set(keyOf(stream.convoId), stream);
            try {
                stream.handle = openChatStream(submission, localize);
            } catch (err) {
                // Opening the stream is the only synchronous failure point; if it
                // throws, nothing will ever call onEnd, so unwind here or the
                // input stays locked on a turn that never started.
                console.error("[AiChat] failed to open chat stream:", err);
                deregister();
                setIsStreaming(false);
            }
        },
        [conversationId, isStreaming, chatModel, selectedOrgKbs, searchType, selectedAgentTools, dailyTaskSkills, isLingsi, createLinsight, updateLinsight, localize, showToast, queryClient, bsConfig, setBucket, setStreamingFlag, setTitleFor, promoteConversation, keyOf, streamFor]
    );

    // --- Stop generating (the conversation on screen, not every live turn) ---
    const stopGenerating = useCallback(() => {
        const cid = internalConvoIdRef.current;
        const stream = streamFor(cid);
        setStreamingFlag(cid, false);
        if (!stream) return;
        liveStreams.delete(keyOf(cid));
        // close() dispatches `cancel` for a still-open stream, which routes
        // through the same watchdog as a natural end, so onEnd still fires once.
        stream.handle.close();
    }, [setStreamingFlag, streamFor, keyOf]);

    // --- Clear conversation ---
    const clearConversation = useCallback(() => {
        stopGenerating();
        setBucket("new", []);
        setTitleFor("new", "");
        setConversationId("new");
    }, [stopGenerating, setBucket, setTitleFor]);

    const recoverRateLimitedMessage = useCallback(
        (command: ModelRecoveryCommand): Promise<ModelRecoveryResponse> => {
            const targetMessage = messagesRef.current.find(
                (message) => message.executionId === command.executionId,
            );
            if (!targetMessage || isStreaming) {
                return Promise.resolve({
                    execution_id: command.executionId,
                    attempt_id: command.attemptId,
                    accepted: false,
                });
            }

            const parentMessage = messagesRef.current.find(
                (message) => message.messageId === targetMessage.parentMessageId,
            ) ?? ({
                messageId: targetMessage.parentMessageId,
                parentMessageId: NO_PARENT,
                conversationId,
                sender: "user",
                text: "",
                isCreatedByUser: true,
            } satisfies ChatMessage);
            const targetMessageId = targetMessage.messageId;
            const request = buildModelRecoveryRequest({ entry: 'daily' }, command);
            const baseUrl = (__APP_ENV__.BASE_URL || '').replace(/\/$/, '');
            const stream: LiveStream = {
                convoId: targetMessage.conversationId || conversationId,
                ownerId: ownerIdRef.current,
                handle: { close: () => undefined },
            };
            const setMessages = (
                updater: ChatMessage[] | ((previous: ChatMessage[]) => ChatMessage[]),
            ) => setBucket(stream.convoId, updater);
            const setIsStreaming = (value: boolean) => setStreamingFlag(stream.convoId, value);
            const updateActiveMessage = (
                updater: (message: ChatMessage) => ChatMessage,
            ) => {
                setMessages((previous) => {
                    const messages = [...previous];
                    const index = messages.findIndex(
                        (message) => message.executionId === command.executionId
                            || message.messageId === targetMessageId,
                    );
                    if (index < 0 || messages[index].attemptId !== command.attemptId) return previous;
                    messages[index] = updater(messages[index]);
                    return messages;
                });
            };

            setMessages((previous) => previous.map((message) => (
                message.executionId === command.executionId || message.messageId === targetMessageId
                    ? {
                        ...message,
                        attemptId: command.attemptId,
                        error: false,
                        errorText: undefined,
                        errorDetail: undefined,
                        unfinished: true,
                    }
                    : message
            )));
            setIsStreaming(true);
            liveStreams.set(keyOf(stream.convoId), stream);

            return new Promise<ModelRecoveryResponse>((resolve, reject) => {
                let settled = false;
                let accepted = true;
                let recoveryErrorType: string | undefined;
                const settle = () => {
                    if (settled) return;
                    settled = true;
                    setIsStreaming(false);
                    if (streamFor(stream.convoId) === stream) {
                        liveStreams.delete(keyOf(stream.convoId));
                    }
                    void queryClient.invalidateQueries([QueryKeys.bishengConfig]);
                    resolve({
                        execution_id: command.executionId,
                        attempt_id: command.attemptId,
                        accepted,
                        error_type: recoveryErrorType,
                    });
                };

                const submission: SSESubmission = {
                    payload: request.body,
                    sseUrl: `${baseUrl}${request.url}`,
                    userMessage: parentMessage,
                    onStart: () => setIsStreaming(true),
                    onCreated: () => undefined,
                    onMessage: (text, messageId) => updateActiveMessage((message) => ({
                        ...message,
                        text,
                        ...(messageId ? { messageId } : {}),
                    })),
                    onAgentUpdate: (patch) => updateActiveMessage((message) => ({
                        ...message,
                        category: patch.category ?? message.category ?? 'agent_answer',
                        ...(patch.messageId ? { messageId: patch.messageId } : {}),
                        ...(patch.text != null ? { text: patch.text } : {}),
                        ...(patch.events ? { events: patch.events } : {}),
                        ...(patch.finalised ? { unfinished: false } : {}),
                    })),
                    onFinal: (data) => updateActiveMessage((message) => ({
                        ...message,
                        ...(data.responseMessage ?? {}),
                        executionId: command.executionId,
                        attemptId: command.attemptId,
                        error: false,
                        unfinished: false,
                        rateLimitState: 'normal',
                    })),
                    onError: (error, errorCode, meta) => {
                        if (meta?.attemptId && meta.attemptId !== command.attemptId) return;
                        observeModelRateLimitEvent(queryClient, meta);
                        accepted = false;
                        recoveryErrorType = meta?.errorType;
                        updateActiveMessage((message) => ({
                            ...message,
                            error: true,
                            errorText: error,
                            errorCode,
                            errorType: meta?.errorType,
                            executionId: meta?.executionId ?? command.executionId,
                            attemptId: meta?.attemptId ?? command.attemptId,
                            recoverySubjectId: meta?.recoverySubjectId ?? command.subjectId,
                            modelId: meta?.modelId ?? message.modelId,
                            rateLimitState: meta?.rateLimitState,
                            resumeMode: meta?.resumeMode,
                            unfinished: meta?.errorType === 'rate_limit',
                            // F051 never renders or stores raw rate-limit detail.
                            errorDetail: meta?.errorType === 'rate_limit' ? undefined : meta?.errorDetail,
                        }));
                    },
                    onEnd: settle,
                };

                try {
                    stream.handle = openChatStream(submission, localize);
                } catch (error) {
                    setIsStreaming(false);
                    liveStreams.delete(keyOf(stream.convoId));
                    reject(error);
                }
            });
        },
        [conversationId, isStreaming, keyOf, localize, queryClient, setBucket, setStreamingFlag, streamFor],
    );

    // --- Regenerate: add a new sibling response under the same parent ---
    const regenerate = useCallback(
        (parentMessageId: string) => {
            if (isStreaming) return;

            // Find the parent (user) message
            const parentMsg = messagesRef.current.find(
                (m) => m.messageId === parentMessageId
            );
            if (!parentMsg) return;

            // Same conversation-scoped wiring as sendMessage: the regenerated
            // answer belongs to this chat, not to whichever one is on screen
            // when the tokens arrive.
            const stream: LiveStream = {
                convoId: conversationId,
                ownerId: ownerIdRef.current,
                handle: { close: () => { /* not open yet */ } },
            };
            const setMessages = (
                updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[]),
            ) => setBucket(stream.convoId, updater);
            const setIsStreaming = (value: boolean) => setStreamingFlag(stream.convoId, value);
            const bindConversation = (newId: string) => {
                if (!newId || newId === stream.convoId) return;
                const viewingThisTurn = internalConvoIdRef.current === stream.convoId;
                promoteConversation(stream, newId);
                if (viewingThisTurn) setConversationId(newId);
            };
            const deregister = () => {
                if (streamFor(stream.convoId) === stream) {
                    liveStreams.delete(keyOf(stream.convoId));
                }
            };

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
                        bindConversation(newConvoId);
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
                        bindConversation(data.conversation.conversationId);
                    }
                },
                // Same as the send path: failure copy goes to `errorText` so a
                // partially-streamed answer survives the error.
                onError: (error, errorCode, meta) => {
                    observeModelRateLimitEvent(queryClient, meta);
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
                                errorType: meta?.errorType,
                                errorDetail: meta?.errorDetail,
                                executionId: meta?.executionId,
                                attemptId: meta?.attemptId,
                                recoverySubjectId: meta?.recoverySubjectId,
                                modelId: meta?.modelId,
                                rateLimitState: meta?.rateLimitState,
                                resumeMode: meta?.resumeMode,
                                unfinished: meta?.errorType === "rate_limit",
                            };
                        }
                        return msgs;
                    });
                },
                onEnd: () => {
                    setIsStreaming(false);
                    deregister();
                },
            };

            setIsStreaming(true);
            liveStreams.set(keyOf(stream.convoId), stream);
            try {
                stream.handle = openChatStream(submission, localize);
            } catch (err) {
                console.error("[AiChat] failed to open regenerate stream:", err);
                deregister();
                setIsStreaming(false);
            }
        },
        [conversationId, isStreaming, chatModel, selectedOrgKbs, searchType, selectedAgentTools, localize, bsConfig, isLingsi, setBucket, setStreamingFlag, promoteConversation, keyOf, streamFor]
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
        recoverRateLimitedMessage,
        setConversationId,
    };
}
