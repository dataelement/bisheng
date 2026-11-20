/**
 * Core chat state hook — manages messages, submission, and SSE lifecycle.
 * Uses useState/useRef for local state, Recoil only for shared atoms (chatModel, searchType).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRecoilState } from "recoil";
import { v4 } from "uuid";
import type { ConversationData, TConversation } from "~/types/chat";
import { QueryKeys, dataService } from "~/types/chat";
import { addConversation, updateConvoFields } from "~/utils";
import store from "~/store";
import type { SelectedOrgKb } from "~/store/modeltype";
import { useAuthContext } from "~/hooks/AuthContext";
import { knowledgeSpaceTagFilters } from "~/utils/knowledgeTagSelection";
import { canProcessChatImage } from "~/common/chatAccept";
import { useKnowledgeSpaceAccess } from "~/hooks/useKnowledgeSpaceAccess";
import { useConversationKnowledge } from "~/hooks/useConversationKnowledge";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import type { ChatMessage } from "~/api/chatApi";
import { getAgentMessages, getSessionName } from "~/api/chatApi";
import { getMemoryFlagsApi, mergeMemoryFlags } from "~/api/memory";
import { openChatStream, type ChatStreamHandle, type SSESubmission } from "~/hooks/useAiChatSSE";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { refreshInviteQuota } from "~/hooks/inviteQuotaRefresh";
import { useLinsightManager } from "~/hooks/useLinsightManager";
import { taskModeSkillsState } from "~/store/linsight";
import { isMediaAttachmentFile, type MediaParsingState } from "~/utils/mediaAttachmentUtils";
import { useDesktopConversationActivity, useDesktopConversationRenamed } from "~/components/Chat/desktopConversationBridge";
import { runningConversationIds } from "~/components/Chat/runningConversations";
import { bindProjectChatCreation, captureProjectChatDraft } from "~/layouts/WorkbenchSidebar/projectChatCreation";
import { useUnifiedRun } from "~/hooks/useUnifiedRun";

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
const EMPTY_MESSAGES: ChatMessage[] = [];

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

export default function useAiChat(
    initialConversationId: string = "new",
    isLingsi: boolean = false,
    shareToken: string = "",
    draftScope = "chat",
    /**
     * Department page lease accessor for this session page. Returns the lease id
     * to send (or null for pages that do not count) and whether the department
     * is full, in which case the turn must not be sent.
     */
    ensureFlowLeaseId?: () => Promise<{ leaseId: string | null; blocked: boolean }>,
    draftIdentity = "",
) {
    const [historyError, setHistoryError] = useState<unknown>(null);
    const [historyReload, setHistoryReload] = useState(0);
    const retryHistory = () => setHistoryReload(value => value + 1);
    const localize = useLocalize();
    const { showToast } = useToastContext();
    // --- Local state ---
    // Bucketed by conversation: switching only changes which bucket renders, so
    // a turn the user walked away from keeps writing into its own.
    const [messagesByConvo, setMessagesByConvo] = useState<Record<string, ChatMessage[]>>({});
    const [titleByConvo, setTitleByConvo] = useState<Record<string, string>>({});
    const [streamingByConvo, setStreamingByConvo] = useState<Record<string, boolean>>({});
    const [loadingByConvo, setLoadingByConvo] = useState<Record<string, boolean>>({});
    const [parsingMediaByConvo, setParsingMediaByConvo] = useState<Record<string, boolean>>({});
    const [conversationId, setConversationId] = useState(initialConversationId);
    // Formal sessions retain their server id; unsaved drafts need a distinct
    // bucket so a same-URL new-chat action cannot revive a failed earlier turn.
    const draftBucketId = draftIdentity ? `new:${draftScope}:${draftIdentity}` : 'new';
    const activeBucketId = conversationId === 'new' ? draftBucketId : conversationId;
    const activeBucketRef = useRef(activeBucketId);
    activeBucketRef.current = activeBucketId;

    // What the caller sees: the active conversation's slice of the above.
    const messages = messagesByConvo[activeBucketId] ?? EMPTY_MESSAGES;
    const title = titleByConvo[activeBucketId] ?? "";
    const isStreaming = !!streamingByConvo[activeBucketId];
    const isLoading = !!loadingByConvo[activeBucketId];
    const isParsingMedia = !!parsingMediaByConvo[activeBucketId];

    // Identifies this hook instance inside the shared registry.
    const ownerIdRef = useRef<string>("");
    if (!ownerIdRef.current) ownerIdRef.current = v4();

    // Every write names the conversation it targets, because a turn's callbacks
    // may well fire while the user is reading a different chat.
    const setMessagesFor = useCallback(
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
    const setStreamingFor = useCallback((cid: string, value: boolean) => {
        setStreamingByConvo((prev) => (!!prev[cid] === value ? prev : { ...prev, [cid]: value }));
    }, []);
    const setLoadingFor = useCallback((cid: string, value: boolean) => {
        setLoadingByConvo((prev) => (!!prev[cid] === value ? prev : { ...prev, [cid]: value }));
    }, []);
    const setParsingMediaFor = useCallback((cid: string, value: boolean) => {
        setParsingMediaByConvo((prev) => (!!prev[cid] === value ? prev : { ...prev, [cid]: value }));
    }, []);
    const discardUnsavedBucket = useCallback((bucketId: string) => {
        if (bucketId !== 'new' && !bucketId.startsWith('new:')) return;
        const remove = <T,>(previous: Record<string, T>): Record<string, T> => {
            if (!(bucketId in previous)) return previous;
            const next = { ...previous };
            delete next[bucketId];
            return next;
        };
        setMessagesByConvo(remove);
        setTitleByConvo(remove);
        setStreamingByConvo(remove);
        setLoadingByConvo(remove);
        setParsingMediaByConvo(remove);
    }, []);

    /** Move a turn's buckets when it learns its real conversation id, so the
     *  answer the user is watching is still there once the URL catches up. */
    const promoteBucket = useCallback((from: string, to: string) => {
        if (!to || to === from) return;
        const move = <T,>(prev: Record<string, T>): Record<string, T> => {
            if (!(from in prev)) return prev;
            const { [from]: carried, ...rest } = prev;
            return { ...rest, [to]: carried };
        };
        setMessagesByConvo(move);
        setTitleByConvo(move);
        setStreamingByConvo(move);
        setLoadingByConvo(move);
        setParsingMediaByConvo(move);
    }, []);

    // The viewed conversation's writers, for everything outside a turn (loading
    // history, clearing, the switch effect).
    const setMessages = useCallback(
        (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) =>
            setMessagesFor(activeBucketId, updater),
        [activeBucketId, setMessagesFor],
    );
    const setTitle = useCallback(
        (updater: string | ((prev: string) => string)) => setTitleFor(activeBucketId, updater),
        [activeBucketId, setTitleFor],
    );
    const setIsStreaming = useCallback(
        (value: boolean) => setStreamingFor(activeBucketId, value),
        [activeBucketId, setStreamingFor],
    );
    const setIsLoading = useCallback(
        (value: boolean) => setLoadingFor(activeBucketId, value),
        [activeBucketId, setLoadingFor],
    );
    const setIsParsingMedia = useCallback(
        (value: boolean) => setParsingMediaFor(activeBucketId, value),
        [activeBucketId, setParsingMediaFor],
    );

    // Refs for accessing latest state in callbacks
    const messagesRef = useRef<ChatMessage[]>([]);
    messagesRef.current = messages;

    // Shared Recoil atoms
    const [chatModel] = useRecoilState(store.chatModel);
    const [searchType] = useRecoilState(store.searchType);
    // v2.5 Agent-mode: tools toggled on in the chat input bar. Non-empty
    // means the backend dispatcher routes to the LangGraph Agent flow (which
    // emits the new ChatResponse SSE format). Empty array keeps us on the
    // legacy flow so existing tests / old clients aren't disrupted.
    const [selectedAgentTools] = useRecoilState(store.selectedAgentTools);
    // Task-mode requests carry the explicit skill selection.
    const [dailyTaskSkills] = useRecoilState(taskModeSkillsState('new'));
    // Admin-level org-KB toggle. Knowledge spaces remain available even when
    // the org knowledge base feature is disabled, so we only strip org ids.
    const { data: bsConfig } = useGetBsConfig();

    // F004: the conversation page sends with `X-BS-Run-Protocol: 2` and reads
    // the answer from the run event stream. The other carriers of this hook
    // (the subscription dock, a share view) are outside that protocol: there
    // `unified` stays inert and a send opens the page-owned stream below.
    const usesRunProtocol = draftScope === "chat" && !isLingsi && !shareToken;
    const unified = useUnifiedRun({
        enabled: usesRunProtocol,
        conversationId,
        bucketId: activeBucketId,
        messages,
        isLoading,
        setMessagesFor,
        sender: chatModel.name || "AI",
    });
    const { user } = useAuthContext();
    const knowledgeDefaults = useMemo<SelectedOrgKb[]>(() => bsConfig?.knowledgeBase?.enabled === false
        ? [] : (bsConfig?.orgKbs ?? []).filter((kb) => kb.default_checked)
            .map((kb) => ({ id: String(kb.id), name: kb.name, type: 'org' })), [bsConfig]);
    const { selectedOrgKbs: savedKnowledge, setSelectedOrgKbs, promoteSelection } = useConversationKnowledge(
        user?.id == null ? undefined : String(user.id), conversationId, knowledgeDefaults,
        bsConfig?.knowledgeBase?.enabled !== false, draftScope,
    );

    const { available: selectedOrgKbs, message: knowledgeAccessMessage, blocked: knowledgeAccessBlocked } =
        useKnowledgeSpaceAccess(savedKnowledge, `${draftScope}:${conversationId}`, !shareToken);

    const queryClient = useQueryClient();

    // Stored deep-research turns hydrate into the linsight store; its running
    // entries feed the desktop host's activity list below.
    const { linsightMap } = useLinsightManager();

    // The desktop host lists conversations itself; keep its running state and names in step.
    useDesktopConversationActivity(ownerIdRef.current, runningConversationIds(streamingByConvo, linsightMap));
    useDesktopConversationRenamed(useCallback((renamedId: string) => {
        getSessionName(renamedId)
            .then((name) => {
                if (!name) return;
                setTitleFor(renamedId, name);
                queryClient.setQueryData<ConversationData>([QueryKeys.allConversations], (convoData) =>
                    convoData ? updateConvoFields(convoData, { conversationId: renamedId, title: name } as TConversation) : convoData);
            })
            .catch(() => {
                // Non-critical: the header keeps the previous name until the conversation reopens.
            });
    }, [queryClient, setTitleFor]));

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
            let finished = false;
            const entry: LiveStream = { convoId: cid, close: () => { handle.close(); } };
            const handle: ChatStreamHandle = openChatStream({ ...submission, onEnd: () => {
                if (finished) return;
                finished = true;
                const key = streamKey(ownerId, entry.convoId);
                const current = liveStreams.get(key);
                if (current === entry) liveStreams.delete(key);
                // A replaced turn cannot finish a newer stream in the same chat.
                if (current && current !== entry) return;
                submission.onEnd();
                if (entry.convoId !== activeBucketRef.current) discardUnsavedBucket(entry.convoId);
            } }, localize);
            if (!finished) liveStreams.set(streamKey(ownerId, cid), entry);
        },
        [localize, discardUnsavedBucket],
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
        (turn: { cid: string; bucketId: string; knowledge: SelectedOrgKb[] }, next: string) => {
            if (!next || next === turn.cid) return;
            const previousId = turn.cid;
            const previousBucketId = turn.bucketId;
            promoteSelection(previousId, next, turn.knowledge);
            promoteBucket(previousBucketId, next);
            promoteStream(previousBucketId, next);
            turn.cid = next;
            turn.bucketId = next;
            setConversationId((current) => current === previousId && activeBucketRef.current === previousBucketId ? next : current);
        },
        [promoteBucket, promoteStream, promoteSelection],
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

    // A send on "new" binds the conversation to the id the server just minted,
    // which would normally trigger a history refetch. The answer row is not
    // stored yet, so that refetch returns ONLY the user question and clobbers
    // the optimistic turn. This ref tells the load effect to skip exactly that
    // one refetch; the optimistic rows are authoritative for this turn.
    const skipLoadConvoRef = useRef<string | null>(null);

    // Track previous external ID to distinguish sidebar navigation from self-navigate
    const [previousExternalId, setPreviousExternalId] = useState(initialConversationId);
    const [previousDraftIdentity, setPreviousDraftIdentity] = useState(draftIdentity);

    // Resolve sidebar navigation during render so the composer, its callbacks,
    // and the message bucket commit with the same conversation identity.
    if (previousExternalId !== initialConversationId || (initialConversationId === 'new' && previousDraftIdentity !== draftIdentity)) {
        if (initialConversationId === 'new' && previousDraftIdentity !== draftIdentity) {
            const previousBucketId = previousDraftIdentity ? `new:${draftScope}:${previousDraftIdentity}` : 'new';
            if (!streamingByConvo[previousBucketId]) discardUnsavedBucket(previousBucketId);
        }
        setPreviousExternalId(initialConversationId);
        setPreviousDraftIdentity(draftIdentity);
        if (initialConversationId !== conversationId) {
            const arrivingBucketId = initialConversationId === 'new' ? draftBucketId : initialConversationId;
            const arrivingIsLive = !!streamingByConvo[initialConversationId]
                || !!liveStreams.get(streamKey(ownerIdRef.current, arrivingBucketId));
            setLoadingFor(arrivingBucketId, initialConversationId !== "new" && !arrivingIsLive);
            skipLoadConvoRef.current = null;
            setConversationId(initialConversationId);
        }
    }

    // --- Load existing messages when conversationId changes ---
    // Only re-runs when conversationId itself changes — NOT when streaming ends.
    // (isStreaming intentionally excluded from deps: when SSE creates a new convo
    // mid-stream we set the conversationId during streaming; if we re-ran on
    // streaming end we'd refetch and overwrite the just-streamed messages,
    // causing a visible flash on the first reply of a new chat.)
    useEffect(() => {
        setHistoryError(null);
        if (isStreaming) return;
        if (!conversationId || conversationId === "new") {
            return;
        }
        // Skip the one refetch that would clobber the optimistic turn (see
        // skipLoadConvoRef). Consume the guard so a genuine later navigation
        // back to this convo still reloads normally.
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
        let active = true;
        getAgentMessages(conversationId, shareToken || undefined)
            .then((msgs) => {
                if (!active) return;
                // F004: keeps the live row of a run in progress; returns `msgs` as is outside the run protocol.
                setMessages((prev) => unified.composeHistory(conversationId, msgs, prev));
                setIsLoading(false);
                // F132: memory flags are owner-only, so a share view never asks.
                if (shareToken) return;
                getMemoryFlagsApi(conversationId)
                    .then((flags) => {
                        if (!active) return;
                        setMessages((prev) => mergeMemoryFlags(prev, flags));
                    })
                    .catch(() => {
                        /* flags are decoration; the history stays usable without them */
                    });
            })
            .catch((err) => {
                if (!active) return;
                setHistoryError(err);
                setIsLoading(false);
            });
        return () => { active = false; };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally exclude isStreaming
    }, [conversationId, activeBucketId, shareToken, historyReload]);

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
    const finishMediaParsing = useCallback((userMsgId: string, bucketId: string) => {
        setParsingMediaFor(bucketId, false);
        setMessagesFor(bucketId, (prev) => {
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
    }, [setParsingMediaFor, setMessagesFor]);

    const sendMessage = useCallback(
        async (text: string, files?: any[] | null, opts?: { taskMode?: boolean }) => {
            if ((!text.trim() && !(files?.length)) || isStreaming) return false;
            // The lease may take time. Keep this send's original project even if
            // the user opens another draft before the request can be submitted.
            const projectDraft = captureProjectChatDraft(conversationId === "new" ? null : conversationId);
            const turnMessages = messagesRef.current;
            if (knowledgeAccessBlocked) {
                showToast({ message: knowledgeAccessMessage, status: "warning" });
                return false;
            }
            if (opts?.taskMode && selectedOrgKbs.some(item => item.type === 'space' && item.tag)) {
                showToast({ message: localize("com_knowledge.tag_filter_daily_only"), status: "warning" });
                return false;
            }
            const vision = bsConfig?.models?.some(model => String(model.id) === String(chatModel.id) && model.visual) ?? false;
            if (!opts?.taskMode && !isLingsi && files?.some(file => !canProcessChatImage(
                file.name || file.filename || file.file_name || '', vision, !!bsConfig?.enable_etl4lm,
            ))) {
                showToast({ message: localize("chatImage.processingRequired"), status: "warning" });
                return false;
            }
            // Department concurrency (docs/部门流量控制方案.md): take/refresh this
            // page's lease before anything is written to the message list or sent.
            // `blocked` means the department is full — leave the composer state
            // untouched so the user can retry once a slot frees up.
            const presence = ensureFlowLeaseId ? await ensureFlowLeaseId() : null;
            if (presence?.blocked) {
                return false;
            }
            // This turn belongs to the conversation it started in, and every
            // write below must land there even if the user walks away mid-answer.
            // Shadowing the viewed-conversation writers with turn-scoped ones is
            // what makes that true for all of the callbacks at once: `turn.cid`
            // is the single place the id lives, so a mid-stream promotion from
            // "new" to a real id carries the whole turn with it.
            const turn = { cid: conversationId, bucketId: activeBucketId, knowledge: selectedOrgKbs };
            if (activeBucketRef.current === turn.bucketId) setSelectedOrgKbs(turn.knowledge);
            const setMessages = (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) =>
                setMessagesFor(turn.bucketId, updater);
            const setTitle = (updater: string | ((prev: string) => string)) =>
                setTitleFor(turn.bucketId, updater);
            const setIsStreaming = (value: boolean) => setStreamingFor(turn.bucketId, value);
            const setIsParsingMedia = (value: boolean) => setParsingMediaFor(turn.bucketId, value);


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
                    status: "warning",
                });
                return false;
            }

            const filesForDisplay = (files ?? []).map((f) =>
                isMediaAttachmentFile(f) ? { ...f, parsingState: 'parsing' as MediaParsingState } : f,
            );
            const hasMediaAttachments = filesForDisplay.some(isMediaAttachmentFile);
            if (hasMediaAttachments) {
                setIsParsingMedia(true);
            }

            // Strip blob preview URLs and UI-only parsing flags before SSE payload.
            const cleanFiles = filesForDisplay.map(
                ({ previewUrl, mediaPreviewUrl, mediaCoverUrl, parsingState, ...rest }) => rest,
            );

            const parentMsg = turnMessages[turnMessages.length - 1];
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
                files: filesForDisplay,
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
            // F004: under the run protocol the answer row mirrors a run. A run
            // already in progress takes this message (as a steer or as the
            // answer to its question), so no second answer row is added; an
            // idle conversation gets a row that waits for its run id.
            const updatedMessages = !usesRunProtocol
                ? [...turnMessages, userMessage, initialResponse]
                : unified.isBusy(turn.cid)
                    ? [...turnMessages, userMessage]
                    : [...turnMessages, userMessage, { ...initialResponse, liveRunId: "" }];
            setMessages(updatedMessages);

            // Build SSE payload (same structure as useChatFunctions.ask).
            // Backend expects List[int] for both id fields; selections hold strings
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
                    knowledge_space_tag_filters: knowledgeSpaceTagFilters(selectedOrgKbs),
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
                // Deep research: the same entry starts the run with the task profile.
                task_mode: taskMode,
                // Ordinary turns carry an empty skill selection.
                skills: taskMode ? dailyTaskSkills.map((s) => s.name) : [],
                skill_ids: taskMode ? dailyTaskSkills.flatMap((s) => (typeof s.id === 'number' ? [s.id] : [])) : [],
            };

            if (usesRunProtocol) {
                // F004: one JSON answer instead of a stream; the run's progress
                // arrives through the conversation's event subscription.
                setIsStreaming(true);
                const sent = await unified.send({
                    payload: { ...payload, ...bindProjectChatCreation(projectDraft ?? undefined) },
                    flowLeaseId: presence?.leaseId,
                    conversationId: turn.cid,
                    userMessageId,
                    setMessages,
                    onConversation: (serverConvoId) => {
                        if (serverConvoId === turn.cid) return;
                        // The optimistic rows are the truth for this turn; a
                        // refetch now would replace them with the question alone.
                        skipLoadConvoRef.current = serverConvoId;
                        adoptConversationId(turn, serverConvoId);
                    },
                    onRejected: (message) => showToast({ message, status: "error" }),
                });
                setIsStreaming(false);
                finishMediaParsing(userMessageId, turn.bucketId);
                if (!sent.accepted) return false;
                if (taskMode) refreshInviteQuota();
                const sentConvoId = sent.conversationId;
                if (wasNewConvo && sentConvoId) {
                    queryClient.setQueryData<ConversationData>([QueryKeys.allConversations], (convoData) =>
                        convoData ? addConversation(convoData, {
                            conversationId: sentConvoId,
                            title: localize('com_ui_new_chat'),
                            createdAt: new Date().toISOString(),
                            updatedAt: new Date().toISOString(),
                            model: chatModel.name || '',
                            endpoint: '',
                            endpointType: 'custom',
                            isArchived: false,
                            tags: [],
                        } as unknown as TConversation) : convoData);
                    // The endpoint waits until the backend has stored a real name.
                    dataService.genTitle({ conversationId: sentConvoId })
                        .then((res: { title?: string }) => {
                            if (!res?.title) return;
                            setTitle(res.title);
                            queryClient.setQueryData<ConversationData>([QueryKeys.allConversations], (convoData) =>
                                convoData ? updateConvoFields(convoData, {
                                    conversationId: sentConvoId,
                                    title: res.title,
                                } as TConversation) : convoData);
                        })
                        .catch(() => { /* non-critical: the placeholder name stays */ });
                }
                return true;
            }

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
                projectDraft: projectDraft ?? null,
                userMessage,
                flowLeaseId: presence?.leaseId ?? undefined,
                onStart: () => {
                    console.log('[AiChat] SSE stream started');
                    setIsStreaming(true);
                },
                onCreated: (newConvoId, mergedUser) => {
                    console.log('[AiChat] created:', newConvoId, mergedUser);
                    // Only update conversationId if we got a valid value
                    if (newConvoId && newConvoId !== "") {
                        // A content-safety block (and any other turn that finishes
                        // in the same tick the id is minted) lands here with
                        // isStreaming already false. The history effect would then
                        // treat it as a cold open and replace the live turn with
                        // the blank loader. Skip that one refetch.
                        if (newConvoId !== turn.cid) {
                            skipLoadConvoRef.current = newConvoId;
                        }
                        adoptConversationId(turn, newConvoId);

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
                                : m.parentMessageId === userMessageId
                                    ? { ...m, parentMessageId: serverMessageId }
                                    : m
                        )
                    );
                },
                onQuestionFilesUpdate: ({ messageId, files: updatedFiles }) => {
                    if (!updatedFiles?.length) return;
                    setMessages((prev) =>
                        prev.map((m) => {
                            if (!m.isCreatedByUser || !m.files?.length) return m;
                            const matchesTarget =
                                (messageId && (m.messageId === messageId || String(m.messageId) === messageId))
                                || m.messageId === realUserMessageId
                                || m.messageId === userMessageId;
                            if (!matchesTarget) return m;
                            const byKey = new Map(
                                updatedFiles.map((f: any) => [
                                    String(f.file_id || f.filepath || f.id || ''),
                                    f,
                                ]),
                            );
                            return {
                                ...m,
                                files: m.files.map((mf: any) => {
                                    const key = String(mf.file_id || mf.filepath || mf.id || '');
                                    const next = byKey.get(key);
                                    if (!next?.cover_filepath) return mf;
                                    return {
                                        ...mf,
                                        cover_filepath: next.cover_filepath,
                                        parsingState: 'done' as MediaParsingState,
                                    };
                                }),
                            };
                        }),
                    );
                },
                onMessage: (text, messageId) => {
                    finishMediaParsing(realUserMessageId, turn.bucketId);
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
                    finishMediaParsing(realUserMessageId, turn.bucketId);
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
                            ...(patch.files ? { files: patch.files } : {}),
                            ...(patch.finalised ? { unfinished: false } : {}),
                            ...(patch.memory ? { memory: patch.memory } : {}),
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
                        if (data.conversation.conversationId !== turn.cid) {
                            skipLoadConvoRef.current = data.conversation.conversationId;
                        }
                        adoptConversationId(turn, data.conversation.conversationId);
                    }
                    // New conversation: fetch the AI-generated title. The gen_title
                    // endpoint waits until the backend's background task persists a
                    // real name, so this no longer races slow models (>5s).
                    const finalConvoId = data.conversation?.conversationId || turn.cid;
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
                    finishMediaParsing(realUserMessageId, turn.bucketId);
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
                                referenceId: meta?.referenceId,
                                failureInfo: meta?.failureInfo,
                            };
                        }
                        return msgs;
                    });
                },
                onEnd: () => {
                    finishMediaParsing(realUserMessageId, turn.bucketId);
                    setIsStreaming(false);
                },
            };

            // Lock input immediately — don't wait for SSE open event
            setIsStreaming(true);
            beginStream(turn.bucketId, submission);
            return true;
        },
        [knowledgeAccessBlocked, knowledgeAccessMessage, conversationId, activeBucketId, isStreaming, chatModel, selectedOrgKbs, setSelectedOrgKbs, bsConfig, adoptConversationId, searchType, selectedAgentTools, dailyTaskSkills, isLingsi, localize, showToast, queryClient, finishMediaParsing, ensureFlowLeaseId, usesRunProtocol, unified.isBusy, unified.send]
    );

    // --- Stop generating ---
    const unifiedStopRun = unified.stopRun;
    // Read through a ref: `localize` has a new identity on every render and
    // must not make `stopGenerating` change with it.
    const notifyStopFailedRef = useRef<() => void>(() => undefined);
    notifyStopFailedRef.current = () => showToast({ message: localize("runComposer.stopFailed"), status: "error" });
    const stopGenerating = useCallback(() => {
        // Only the conversation being read. A turn generating in another one is
        // none of this button's business.
        endStream(activeBucketId);
        setIsStreaming(false);
        setIsParsingMedia(false);
        // F004: a run lives on the server; ask it to
        // stop. The `run_stopped` event ends it on screen. No-op otherwise.
        unifiedStopRun().catch((err: { presentation?: string } | null) => {
            // The run keeps going and the stop button stays available. Say so,
            // unless the request layer already showed this failure.
            if (err?.presentation === "toast" || err?.presentation === "global") return;
            notifyStopFailedRef.current();
        });
    }, [activeBucketId, endStream, setIsParsingMedia, setIsStreaming, unifiedStopRun]);

    // --- Clear conversation ---
    const clearConversation = useCallback(() => {
        stopGenerating();
        setMessages([]);
        setConversationId("new");
        setTitle("");
    }, [setMessages, setTitle, stopGenerating]);

    // --- Regenerate: add a new sibling response under the same parent ---
    const regenerate = useCallback(
        async (parentMessageId: string) => {
            if (isStreaming || unified.isRunning) return;
            if (usesRunProtocol) {
                // F004: the run protocol has no "regenerate": a conversation
                // is one linear thread and every request stores a new question
                // row. So this entry (also the "retry" of a failed answer)
                // sends the question again through the normal send, which
                // starts a new run. The page-owned stream below would open
                // next to the run store: the composer stays open during a
                // run but `sendMessage` refuses while that stream is going.
                // Attachments are not sent again: the files of the earlier
                // turn are already in the conversation's workspace.
                const question = messagesRef.current.find(
                    (m) => m.isCreatedByUser && m.messageId === parentMessageId,
                );
                const text = question?.text?.trim();
                if (text) await sendMessage(text, null);
                return;
            }
            const projectDraft = captureProjectChatDraft(conversationId === "new" ? null : conversationId);
            const turnMessages = messagesRef.current;
            if (knowledgeAccessBlocked) {
                showToast({ message: knowledgeAccessMessage, status: "warning" });
                return;
            }
            // Department concurrency: same rule as a fresh send — check before the
            // placeholder bubble is added, so a full department leaves no stray
            // empty answer behind.
            const presence = ensureFlowLeaseId ? await ensureFlowLeaseId() : null;
            if (presence?.blocked) {
                return;
            }
            // This turn belongs to the conversation it started in, and every
            // write below must land there even if the user walks away mid-answer.
            // Shadowing the viewed-conversation writers with turn-scoped ones is
            // what makes that true for all of the callbacks at once: `turn.cid`
            // is the single place the id lives, so a mid-stream promotion from
            // "new" to a real id carries the whole turn with it.
            const turn = { cid: conversationId, bucketId: activeBucketId, knowledge: selectedOrgKbs };
            if (activeBucketRef.current === turn.bucketId) setSelectedOrgKbs(turn.knowledge);
            const setMessages = (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) =>
                setMessagesFor(turn.bucketId, updater);
            const setIsStreaming = (value: boolean) => setStreamingFor(turn.bucketId, value);



            // Find the parent (user) message
            const parentMsg = turnMessages.find(
                (m) => m.isCreatedByUser && m.messageId === parentMessageId
            );
            if (!parentMsg) return;
            const vision = bsConfig?.models?.some(model => String(model.id) === String(chatModel.id) && model.visual) ?? false;
            if (parentMsg.files?.some(file => !canProcessChatImage(
                file.name || file.filename || file.file_name || '', vision, !!bsConfig?.enable_etl4lm,
            ))) {
                showToast({ message: localize("chatImage.processingRequired"), status: "warning" });
                return;
            }

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

            // Each server event can replace the temporary answer ID. Capture
            // the preceding ID so batched updates keep targeting the same row.
            let responseMessageId = newResponseId;
            const updateResponse = (patch: Partial<ChatMessage>) => {
                const previousId = responseMessageId;
                responseMessageId = patch.messageId || responseMessageId;
                setMessages((prev) => prev.map((message) =>
                    message.messageId === previousId ? { ...message, ...patch } : message,
                ));
            };

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
                    knowledge_space_tag_filters: knowledgeSpaceTagFilters(selectedOrgKbs),
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

            // Department concurrency: the lease was checked at the top of this
            // callback, before any placeholder was added.
            const submission: SSESubmission = {
                payload,
                projectDraft: projectDraft ?? null,
                userMessage: parentMsg,
                flowLeaseId: presence?.leaseId ?? undefined,
                onStart: () => {
                    console.log("[AiChat] Regenerate SSE started");
                    setIsStreaming(true);
                },
                onCreated: (newConvoId, mergedUser) => {
                    if (newConvoId && newConvoId !== "") {
                        adoptConversationId(turn, newConvoId);
                    }
                    const questionId = String(mergedUser.messageId || parentMsg.messageId);
                    setMessages((prev) => prev.map((message) =>
                        message.messageId === parentMsg.messageId
                            ? { ...message, ...mergedUser, messageId: questionId }
                            : message.parentMessageId === parentMsg.messageId
                                ? { ...message, parentMessageId: questionId }
                                : message,
                    ));
                },
                onMessage: (text, messageId) => {
                    updateResponse({
                        text,
                        ...(messageId ? { messageId } : {}),
                    });
                },
                onAgentUpdate: (patch) => {
                    updateResponse({
                        category: patch.category ?? "agent_answer",
                        ...(patch.messageId ? { messageId: patch.messageId } : {}),
                        ...(patch.text != null ? { text: patch.text } : {}),
                        ...(patch.events ? { events: patch.events } : {}),
                        ...(patch.files ? { files: patch.files } : {}),
                        ...(patch.finalised ? { unfinished: false } : {}),
                        ...(patch.memory ? { memory: patch.memory } : {}),
                    });
                },

                onFinal: (data) => {
                    if (data.responseMessage) updateResponse(data.responseMessage);
                    if (data.conversation?.conversationId) {
                        adoptConversationId(turn, data.conversation.conversationId);
                    }
                },
                // Same as the send path: failure copy goes to `errorText` so a
                // partially-streamed answer survives the error.
                onError: (error, errorCode, meta) => {
                    updateResponse({
                        errorText: error || localize("workstation.chat.answer_failed"),
                        error: true,
                        errorCode,
                        errorType: meta?.errorType,
                        errorDetail: meta?.errorDetail,
                        referenceId: meta?.referenceId,
                        failureInfo: meta?.failureInfo,
                    });
                },
                onEnd: () => {
                    setIsStreaming(false);
                },
            };

            setIsStreaming(true);
            beginStream(turn.bucketId, submission);
        },
        [knowledgeAccessBlocked, knowledgeAccessMessage, conversationId, activeBucketId, isStreaming, unified.isRunning, chatModel, selectedOrgKbs, setSelectedOrgKbs, bsConfig, adoptConversationId, searchType, selectedAgentTools, localize, showToast, ensureFlowLeaseId, usesRunProtocol, sendMessage]
    );

    return {
        historyError,
        isClearing: false,
        retryHistory,
        // State
        // F004: under the run protocol the row of a run in progress shows the
        // run store's state; otherwise this is the bucket as is.
        messages: unified.messages,
        // Legacy alias — kept null to maintain the old destructuring shape
        // without shipping tree-building on the hot path.
        messagesTree: null as unknown,
        conversationId,
        title,
        isLoading,
        // F004: also true while a run of the conversation is in progress.
        isStreaming: isStreaming || unified.isRunning,
        isParsingMedia,

        selectedOrgKbs,
        knowledgeAccessMessage,
        setSelectedOrgKbs,

        // Actions
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
        setConversationId,
        /** A run is in progress (running, or waiting for the user's answer). */
        isRunActive: unified.isRunning,
        /** POST /conversations/{id}/stop for the run on screen. */
        stopRun: unified.stopRun,
    };
}
