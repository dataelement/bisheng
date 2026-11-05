import { useCallback, type MutableRefObject } from 'react';
import type { QueryClient } from '@tanstack/react-query';
import { v4 } from 'uuid';
import type { ConversationData, TConversation } from '~/types/chat';
import { QueryKeys, dataService } from '~/types/chat';
import { addConversation, updateConvoFields } from '~/utils';
import type { ChatMessage } from '~/api/chatApi';
import { startLinsight } from '~/api/linsight';
import { SopStatus } from '~/store/linsight';
import { isMediaAttachmentFile, type MediaParsingState } from '~/utils/mediaAttachmentUtils';
import { requestFailureMetadata } from '~/utils/failureInfo';
import type { SSESubmission } from './useAiChatSSE';
import type { useLocalize } from '~/hooks';
import type { useToastContext } from '~/Providers';
import type { useLinsightManager } from './useLinsightManager';
import type { useChatBuckets } from './useChatBuckets';
import type { useChatAttachmentPoll } from './useChatAttachmentPoll';
const NO_PARENT = '00000000-0000-0000-0000-000000000000';
type Buckets = ReturnType<typeof useChatBuckets>;
type Manager = ReturnType<typeof useLinsightManager>;
interface ChatSendContext extends Pick<Buckets, 'conversationId' | 'isStreaming' | 'setMessagesFor' | 'setTitleFor' | 'setStreamingFor' | 'setParsingMediaFor'> {
    chatModel: { id: string | number; name?: string };
    selectedOrgKbs: { id: string | number; type: string }[];
    selectedAgentTools: { children?: { id: string | number; tool_key: string }[] }[];
    dailyTaskSkills: { name: string }[];
    isLingsi: boolean;
    createLinsight: Manager['createLinsight']; updateLinsight: Manager['updateLinsight'];
    reconcileLinsightFromServer: Manager['reconcileLinsightFromServer'];
    localize: ReturnType<typeof useLocalize>; showToast: ReturnType<typeof useToastContext>['showToast'];
    queryClient: QueryClient; finishMediaParsing: (id: string) => void;
    messagesRef: MutableRefObject<ChatMessage[]>;
    adoptConversationId: (turn: { cid: string }, next: string) => void;
    internalConvoIdRef: MutableRefObject<string>; skipLoadConvoRef: MutableRefObject<string | null>;
    beginStream: (cid: string, submission: SSESubmission) => void;
    bsConfig?: { knowledgeBase?: { enabled: boolean } };
    pollFiles: ReturnType<typeof useChatAttachmentPoll>['pollFiles'];
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

export function useChatSend({ conversationId, isStreaming, chatModel, selectedOrgKbs, selectedAgentTools, dailyTaskSkills, isLingsi, createLinsight, updateLinsight, reconcileLinsightFromServer, localize, showToast, queryClient, finishMediaParsing, messagesRef, setMessagesFor, setTitleFor, setStreamingFor, setParsingMediaFor, adoptConversationId, internalConvoIdRef, skipLoadConvoRef, beginStream, bsConfig, pollFiles }: ChatSendContext) {
    const sendMessage = useCallback(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
        (text: string, files?: any[] | null, opts?: { taskMode?: boolean }) => {
            if ((!text.trim() && !(files?.length)) || isStreaming) return;
            // This turn belongs to the conversation it started in, and every
            // write below must land there even if the user walks away mid-answer.
            // Shadowing the viewed-conversation writers with turn-scoped ones is
            // what makes that true for all of the callbacks at once: `turn.cid`
            // is the single place the id lives, so a mid-stream promotion from
            // "new" to a real id carries the whole turn with it.
            const turn = { cid: conversationId };
            const setMessages = (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) =>
                setMessagesFor(turn.cid, updater);
            const setTitle = (updater: string | ((prev: string) => string)) =>
                setTitleFor(turn.cid, updater);
            const setIsStreaming = (value: boolean) => setStreamingFor(turn.cid, value);
            const setIsParsingMedia = (value: boolean) => setParsingMediaFor(turn.cid, value);


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
                return;
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
            const updatedMessages = [...messagesRef.current, userMessage, initialResponse];
            setMessages(updatedMessages);

            // Build SSE payload (same structure as useChatFunctions.ask).
            // Backend expects List[int] for both id fields; atom holds strings
            // so we coerce via Number here.
            const orgKbDisabled = bsConfig?.knowledgeBase?.enabled === false;
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
                        adoptConversationId(turn, chat_id);
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
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                    } as any);

                    startLinsight(svid)
                        .then(() => updateLinsight(svid, (latest) => [SopStatus.completed, SopStatus.FeedbackCompleted, SopStatus.Stoped].includes(latest.status) ? {} : { status: SopStatus.Running }))
                        .catch(async (err) => {
                            console.error('[AiChat] task start-execute failed:', err);
                            try {
                                if (await reconcileLinsightFromServer(svid, undefined, true)) return;
                            } catch {
                                // Keep the known execution active when its authoritative state is unavailable.
                            }
                            updateLinsight(svid, {
                                taskError: localize('com_linsight.task_start_failed'),
                                taskErrorInfo: requestFailureMetadata(err),
                            });
                        });

                    // The handoff event carries no files. Attachment ingest no longer
                    // runs inside the submit request — the linsight worker materializes
                    // uploads/* just before the run — so at handoff time this SV's row
                    // still has files=[] and the single shot this used to be always
                    // missed, leaving the workspace drawer (uploaded-files group +
                    // header button) empty until a manual refresh. Poll instead: stop
                    // as soon as the files land, stop when the run can no longer
                    // produce any, and give up at INGEST_POLL_DEADLINE_MS so a
                    // pathological batch degrades to "visible after refresh" rather
                    // than to an unbounded timer.
                    pollFiles(chat_id, svid, turn.cid, realUserMessageId, setMessages);

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
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                updatedFiles.map((f: any) => [
                                    String(f.file_id || f.filepath || f.id || ''),
                                    f,
                                ]),
                            );
                            return {
                                ...m,
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
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
                    finishMediaParsing(realUserMessageId);
                    console.log('[AiChat] message:', { text: text?.slice(0, 50), messageId });
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const lastMsg = msgs[msgs.length - 1];
                        if (lastMsg && !lastMsg.isCreatedByUser) {
                            msgs[msgs.length - 1] = {
                                ...lastMsg,
                                text,
                                hasAnswerContent: Boolean(text),
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
                    finishMediaParsing(realUserMessageId);
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
                        adoptConversationId(turn, data.conversation.conversationId);
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
                    finishMediaParsing(realUserMessageId);
                    setMessages((prev) => {
                        const msgs = [...prev];
                        const lastMsg = msgs[msgs.length - 1];
                        if (lastMsg && !lastMsg.isCreatedByUser) {
                            msgs[msgs.length - 1] = {
                                ...lastMsg,
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
                    finishMediaParsing(realUserMessageId);
                    setIsStreaming(false);
                },
            };

            // Lock input immediately — don't wait for SSE open event
            setIsStreaming(true);
            beginStream(turn.cid, submission);
        },
        [conversationId, isStreaming, chatModel, selectedOrgKbs, selectedAgentTools, dailyTaskSkills, isLingsi, createLinsight, updateLinsight, reconcileLinsightFromServer, localize, showToast, queryClient, finishMediaParsing, messagesRef, setMessagesFor, setTitleFor, setStreamingFor, setParsingMediaFor, adoptConversationId, internalConvoIdRef, skipLoadConvoRef, beginStream, bsConfig, pollFiles]
    );

    return sendMessage;
}
