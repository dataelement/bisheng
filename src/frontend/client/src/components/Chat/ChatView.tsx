import { useVisibleKnowledgeSelections } from "./hooks/useVisibleKnowledgeSelections";
import { useTaskModeNavigation } from "./hooks/useTaskModeNavigation";
import { useChatModelSelection } from "./hooks/useChatModelSelection";
import { isApiError } from "@bisheng/api-client";
import { useQuery } from "@tanstack/react-query";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useRecoilState } from "recoil";
import { useTaskInviteQuota } from "~/components/Chat/TaskInviteQuota";
import {
  getLinsightSessionVersionList,
  userStopLinsightEvent,
} from "~/api/linsight";
import { SopStatus, taskModeState } from "~/store/linsight";
import { useCitationReferencePanel } from "~/components/Chat/Messages/Content/useCitationReferencePanel";
import { useDesktopConversation } from "./useDesktopConversation";
import { useAuthContext } from "~/hooks/AuthContext";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/queries";
import useAiChat from "~/hooks/useAiChat";
import { useSessionPresence } from "~/hooks/useSessionPresence";
import {
  moveConversationModel,
  readAdminDefaultModelId,
  type ChatModelMode,
} from "~/hooks/useChatModelResolution";
import { useChatAskHandoff, type ChatAsk } from "./chatAskHandoff";
import useLocalize from "~/hooks/useLocalize";
import store from "~/store";
import { QueryKeys } from "~/types/chat";
import { importMessagesToKnowledgeApi } from "~/api/messageExport";
import { showApiError } from "~/api/request";
import {
  useExitSelectionOnChatChange,
  useMessageSelection,
} from "~/hooks/useMessageSelection";
import usePrefersMobileLayout from "~/hooks/usePrefersMobileLayout";
import useMediaQuery from "~/hooks/useMediaQuery";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { type AddToKnowledgeSelection } from "~/pages/Subscription/Article/AddToKnowledgeModal";
import { useChatSurfaceLayout } from "./hooks/useChatSurfaceLayout";
import { useTaskWorkspaceState } from "./hooks/useTaskWorkspaceState";
import { ChatSurfacePresentation } from "./ChatSurfacePresentation";
import { readNewChatKey } from './newChatDraft';

interface ChatViewProps {
  id?: string;
  index?: number;
  shareToken?: string;
}

function useChatView(
  { id = "", shareToken = "" }: ChatViewProps,
  t: ReturnType<typeof useLocalize>,
  showToast: ReturnType<typeof useToastContext>["showToast"],
) {
  const { conversationId: cid } = useParams();
  const location = useLocation();
  const conversationId = (cid ?? id) || "new";
  // KeepAlive keeps this view mounted on settings routes. Only a chat draft
  // navigation may replace its logical identity or discard its composer.
  const draftIdentityRef = useRef(readNewChatKey(location.state, location.key));
  if (location.pathname === '/c/new') {
    draftIdentityRef.current = readNewChatKey(location.state, location.key);
  }
  const draftIdentity = draftIdentityRef.current;
  const composerIdentity = conversationId === 'new' ? draftIdentity : conversationId;
  const composerIdentityRef = useRef(composerIdentity);
  composerIdentityRef.current = composerIdentity;

  const [inputText, setInputText] = useState("");
  const previousDraftIdentityRef = useRef(draftIdentity);
  useEffect(() => {
    if (conversationId === 'new' && location.pathname === '/c/new' && previousDraftIdentityRef.current !== draftIdentity) {
      previousDraftIdentityRef.current = draftIdentity;
      setInputText('');
    }
  }, [conversationId, draftIdentity, location.pathname]);

  // F035: task mode is a toggle on the daily welcome page — no route jump.
  // The route stays `/c`; only submitting in task mode navigates to /linsight.
  // Driven by a GLOBAL atom (not local state): ChatView is KeepAlive-cached, so a
  // nav-state/effect-based toggle goes stale after returning from another tab.

  // which the re-activated ChatView reads immediately.
  const [taskMode, setTaskMode] = useRecoilState(taskModeState);

  const { data: bsConfig } = useGetBsConfig();
  const { user } = useAuthContext();
  const [chatModel, setChatModel] = useRecoilState(store.chatModel);
  const [searchType, setSearchType] = useRecoilState(store.searchType);
  // Landing-only: the input box reports whether its attachment bar is showing
  // so the welcome subtitle can hide without shifting the title / input box.
  const [landingHasSelection, setLandingHasSelection] = useState(false);

  // Department concurrency: one page lease per session page. Share pages are
  // read-only views of somebody else's session and must not consume a slot.
  const presence = useSessionPresence(
    conversationId === "new" ? "" : conversationId,
    {
      disabled: Boolean(shareToken),
    },
  );

  // Core chat state — replaces old ChatContext + useSSE + useChatHelpers
  const {
    selectedOrgKbs,
    knowledgeAccessMessage,
    setSelectedOrgKbs,
    messages,
    conversationId: activeConvoId,
    title: chatTitle,
    isLoading,
    historyError,
    isClearing,
    retryHistory,
    isStreaming,
    isParsingMedia,
    sendMessage,
    stopGenerating,
    regenerate,
  } = useAiChat(
    conversationId,
    false,
    shareToken,
    "chat",
    presence.ensureLeaseId,
    draftIdentity,
  );

  useVisibleKnowledgeSelections({ user, selectedOrgKbs, setSelectedOrgKbs });

  // Model and knowledge selections are owned by their conversation.
  const { data: workbenchCfg } = useGetWorkbenchModelsQuery();
  const modelMode: ChatModelMode = taskMode ? "task" : "daily";
  const adminDefaultModelId = useMemo(
    () => readAdminDefaultModelId(workbenchCfg, modelMode),
    [workbenchCfg, modelMode],
  );

  const memoReadyRef = useRef(false);
  useEffect(() => {
    if (!bsConfig || !user?.id) return;
    if (memoReadyRef.current) return;
    const prefix = `bs:${user.id}:`;

    // Web search toggle. ChatForm clears searchType on conversation change,
    // but its effect runs before this one (children commit first), so the
    // hydrated value wins on initial mount and survives refresh / new tab.
    try {
      const saved = localStorage.getItem(`${prefix}searchType`);
      if (saved !== null) setSearchType(saved);
    } catch {
      /* ignore */
    }

    memoReadyRef.current = true;
  }, [bsConfig, user?.id, setSearchType]);

  useEffect(() => {
    if (!memoReadyRef.current || !user?.id) return;
    localStorage.setItem(`bs:${user.id}:searchType`, searchType ?? "");
  }, [searchType, user?.id]);

  // ── F028: workstation conversation export / import-to-knowledge ──
  // Auto-exit selection mode whenever the user switches to another chat.
  useExitSelectionOnChatChange(activeConvoId);
  const {
    state: selectionState,
    getSelectedIds,
    exitSelectionMode,
  } = useMessageSelection();
  const isH5 = usePrefersMobileLayout();
  // Matches the CSS `touch-mobile` variant (≤1023px) so the JS-measured apps
  // offset stays in sync with the CSS-based welcome-block centering.
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const { contentWidth, isCompactLayout } =
    useChatSurfaceLayout(chatContainerRef);
  // F035: task-mode workspace panel responsive tiers — mirror the daily-mode
  // citation panel (useCitationReferencePanel): ≤576 full-screen overlay,
  // 577–767 right drawer, 768–1023 portaled right drawer, ≥1024 in-flow docked.
  // isH5 (above) = ≤767; isCompactLayout = ≤1023.
  const isPhoneViewport = useMediaQuery("(max-width: 576px)");
  const [exportSheetOpen, setExportSheetOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);

  const handleImportSelect = useCallback(
    async (selection: AddToKnowledgeSelection) => {
      if (!activeConvoId) return;
      const ids = getSelectedIds(messages);
      const messageIds = ids
        .map((s) => Number.parseInt(s, 10))
        .filter((n) => Number.isFinite(n));
      if (!messageIds.length) return;

      try {
        const resp = await importMessagesToKnowledgeApi({
          chatId: activeConvoId,
          messageIds,
          knowledgeSpaceId: Number(selection.knowledgeSpaceId),
          parentId: selection.folderId ? Number(selection.folderId) : null,
        });
        showToast({
          message:
            t("workstation.messageExport.importSuccess") +
            (resp.dup_renamed ? ` (${resp.target_filename})` : ""),
          severity: NotificationSeverity.SUCCESS,
        });
        setImportModalOpen(false);
        exitSelectionMode();
      } catch (error) {
        if (isApiError(error)) showApiError(error);
        else
          showToast({
            message: t("workstation.messageExport.renderFailed"),
            severity: NotificationSeverity.WARNING,
          });
      }
    },
    [activeConvoId, messages, getSelectedIds, showToast, t, exitSelectionMode],
  );

  const navigate = useNavigate();

  // F035: distinguishes the post-submit URL self-rewrite (same conversation
  // just got its real id — keep the composing mode) from a genuine navigation
  // to a different existing conversation (derive the mode from its history).
  // Set right before the self-rewrite navigate below, consumed by the mode
  // effect once the rewritten URL has landed.
  const keepTaskModeOnRewriteRef = useRef(false);
  // Set when the user flips the toggle by hand. A manual choice has to survive
  // the navigations that happen WITHIN one conversation (see the mode effect
  // below, which otherwise re-derives the mode from the loaded history on every
  // navigation); it is cleared as soon as the conversation itself changes.
  const userToggledRef = useRef(false);
  const lastConversationIdRef = useRef<string | undefined>(conversationId);

  // Sync URL: ONLY when we were on /new and the hook just assigned a real ID.
  // Do NOT navigate if the user is clicking around in the sidebar (that changes
  // conversationId from params which should NOT be overridden by stale activeConvoId).
  useEffect(() => {
    if (conversationId === "new" && activeConvoId && activeConvoId !== "new") {
      // Flag the rewrite so the reset effect above preserves the current mode.
      keepTaskModeOnRewriteRef.current = true;
      // Carry the model picked while composing under `new` to the real id —
      // otherwise the freshly created conversation has no record of its own and
      // resolves from the user-level default instead.
      if (user?.id) {
        moveConversationModel(String(user.id), "new", activeConvoId);
      }
      navigate(`/c/${activeConvoId}`, { replace: true });
    }
  }, [activeConvoId]); // intentionally ONLY on activeConvoId — don't add navigate/conversationId

  // F035: task mode is a ROLE permission. The backend folds each role's
  // menu_ids into web_menu → client `user.plugins`; `linsight_task_mode` is the
  // workbench-home sub-capability toggled per role in the admin console. When
  // the current user's role lacks it, hide the input's task-mode entry + skill

  // plugins absent / non-array → allow (matches the NewChat default, and keeps
  // super-admin/dept-admin — who always carry the key — unaffected).
  const canUseTaskMode = useMemo(() => {
    const plugins = (user as any)?.plugins;
    return Array.isArray(plugins)
      ? plugins.includes("linsight_task_mode")
      : true;
  }, [user]);

  const inviteOn =
    taskMode &&
    canUseTaskMode &&
    !!(bsConfig as { linsight_invitation_code?: boolean } | undefined)
      ?.linsight_invitation_code;
  const {
    bar: inviteQuotaBar,
    dialog: inviteQuotaDialog,
    allowSend: allowInviteSend,
  } = useTaskInviteQuota(inviteOn);

  const handleSend = useCallback(
    async (text: string, files?: any[] | null) => {
      const isTaskTurn = taskMode && canUseTaskMode;
      if (isTaskTurn && !allowInviteSend()) return false;
      // Capture the turn's resources before resetting its composer draft. A
      // `false` result (e.g. the department is full) keeps the draft so the
      // user can send again once a slot frees up.
      const sendingIdentity = composerIdentity;
      const accepted = await sendMessage(text, files, { taskMode: isTaskTurn });
      if (accepted && composerIdentityRef.current === sendingIdentity) setInputText("");
      return accepted;
    },
    [taskMode, canUseTaskMode, sendMessage, allowInviteSend, composerIdentity],
  );

  const isNew = conversationId === "new";
  const hasMessages = messages.length > 0;
  const {
    activeCitationMessageId,
    citationPanelElement,
    onOpenCitationPanel,
    closeCitationPanel,
  } = useCitationReferencePanel({ hasMessages, contentWidth });

  // F035: the task checklist is pinned above the input (Figma 12221-39902 /
  // 12221-40080) for the conversation's latest task turn — it tracks that turn's
  // execution detail from the linsight store rather than scrolling away in the
  // message stream.
  const taskVersionIds = useMemo(() => {
    const ids: string[] = [];
    const seen = new Set<string>();
    for (const message of messages) {
      const m = message as any;
      const versionId =
        m?.category === "task" ? m?.linsightSessionVersionId : "";
      if (versionId && !seen.has(versionId)) {
        seen.add(versionId);
        ids.push(versionId);
      }
    }
    return ids;
  }, [messages]);
  const latestTaskVersionId = taskVersionIds[taskVersionIds.length - 1] || "";

  // F035: a conversation that already holds a task turn IS a task-mode
  // conversation. Guard on the message's own conversationId so the stale
  // previous-conversation message list that lingers for one commit during a
  // navigation transition can't misfire (loaded rows carry chat_id, the
  // optimistic promote carries the real chat_id — both equal conversationId
  // once we're settled on this conversation).
  const isTaskConversation = useMemo(
    () =>
      messages.some(
        (m: any) =>
          m?.category === "task" &&
          m?.linsightSessionVersionId &&
          m?.conversationId === conversationId,
      ),
    [messages, conversationId],
  );

  // Model selection is scoped PER CONVERSATION (bs:{uid}:convModel:{mode}:{id}),
  // not per user: picking a model in conversation A used to change what every
  // other conversation showed, and opening a historical one displayed the last
  // global pick rather than the model that conversation ran on. The user-level
  // record survives as the layer a BRAND-NEW conversation inherits from.
  //
  // Task conversations additionally carry a cross-device source of truth — the
  // model their last turn really executed with (linsight_session_version.model,
  // already returned by session-version-list). It only applies when this browser
  // has no record for the conversation, i.e. after a device/browser switch.
  const { data: taskConversationModelId = null } = useQuery(
    [QueryKeys.linsightSessionVersions, conversationId, shareToken],
    async () => {
      const versions = await getLinsightSessionVersionList(
        conversationId,
        shareToken || "",
      );
      const latest = (versions || [])[(versions || []).length - 1];
      return latest?.model ? String(latest.model) : null;
    },
    {
      enabled: isTaskConversation && conversationId !== "new",
      staleTime: 60_000,
      // A failure here just means we fall through to the local records.
      retry: false,
    },
  );

  const { handleModelChange, handleModelAutoChange } = useChatModelSelection({
    conversationId,
    bsConfig,
    user,
    setChatModel,
    modelMode,
    adminDefaultModelId,
    taskConversationModelId,
  });

  useTaskModeNavigation({
    location,
    conversationId,
    setTaskMode,
    keepTaskModeOnRewriteRef,
    userToggledRef,
    lastConversationIdRef,
    canUseTaskMode,
    isTaskConversation,
  });

  const leaveTaskMode = useCallback(() => setTaskMode(false), [setTaskMode]);
  const selectAskModel = useCallback(
    (modelId: number) => {
      const available = bsConfig?.models?.some(
        (model) => String(model.id) === String(modelId),
      );
      if (!available) return false;
      handleModelChange(modelId);
      return true;
    },
    [bsConfig?.models, handleModelChange],
  );
  const handleAskModelUnavailable = useCallback(
    (ask: ChatAsk) => {
      setInputText(ask.text);
      showToast?.({
        message: t("com_knowledge.ask_model_unavailable"),
        severity: NotificationSeverity.WARNING,
      });
    },
    [showToast, t],
  );
  const { attachmentAsk, retireAttachmentAsk, isTextAskPending } =
    useChatAskHandoff({
      conversationId,
      activeConversationId: activeConvoId,
      locationKey: location.key,
      selectedKbs: selectedOrgKbs,
      setSelectedKbs: setSelectedOrgKbs,
      sendMessage,
      ready: modelMode === "daily" && !!user?.id && !!bsConfig?.models,
      selectedModelId: chatModel.id,
      selectModel: selectAskModel,
      onModelUnavailable: handleAskModelUnavailable,
      onTake: leaveTaskMode,
    });
  useDesktopConversation(
    conversationId,
    isNew && !hasMessages && !isStreaming && !isTextAskPending,
  );

  // Flipping the toggle by hand pins the mode for the rest of this conversation
  // — without the flag, the effect above would re-derive it from the history on
  // the next navigation and undo the user's choice.
  const handleToggleTaskMode = useCallback(() => {
    userToggledRef.current = true;
    setTaskMode((v) => !v);
  }, [setTaskMode]);

  // F035: workspace drawer for the chat-embedded task mode. Lifted to ChatView
  // (the task turn renders inline per message, but the entry button lives in the
  // shared header). Execution state remains bound to the LATEST task turn, while
  // the file list accumulates formal artifacts from every task turn because the
  // workspace itself belongs to the conversation. The drawer only opens on the
  // header button — no auto-expand (the entry icon appearing is enough).
  const {
    updateLinsight,
    taskArtifacts,
    chatAttachments,
    dockedCardRef,
    compareFreeze,
    fsMounted,
    setFsMounted,
    fsExpanded,
    fsBox,
    taskLinsight,
    taskWorkspaceFiles,
    reportTaskTurnLoadFailed,
    taskWorkspaceLoadState,
    taskRunning,
    awaitingUserInput,
  } = useTaskWorkspaceState({
    conversationId,
    messages,
    chatContainerRef,
    isCompactLayout,
    closeCitationPanel,
    taskVersionIds,
    latestTaskVersionId,
  });

  // Stop button handler. A task round runs via the linsight worker/WS, normally
  // AFTER the handoff SSE stream closed — route the stop to terminate-execute.
  const handleStop = useCallback(() => {
    if (taskRunning && latestTaskVersionId) {
      userStopLinsightEvent(latestTaskVersionId).catch(() => {
        /* best-effort: WS task_terminated reconciles */
      });
      updateLinsight(latestTaskVersionId, (prev) => ({
        ...prev,
        status: SopStatus.Stoped,
        tasks: (prev.tasks || []).map((tk: any) => ({
          ...tk,
          status: tk.status === "in_progress" ? "terminated" : tk.status,
          children: tk.children
            ? tk.children.map((c: any) => ({
                ...c,
                status: c.status === "in_progress" ? "terminated" : c.status,
              }))
            : tk.children,
        })),
      }));
      // The handoff SSE may still be open when the user stops quickly (esp. while
      // queued): isStreaming would then keep the input's stop button lit after the
      // terminate, since the button gates on `isStreaming || taskRunning` and only
      // taskRunning flipped here. Abort the (now-useless) handoff stream + clear
      // isStreaming so the input syncs to the stopped state immediately instead of
      // lingering until the stream drops on its own. (QA: stop-while-queued.)
      stopGenerating();
      return;
    }
    stopGenerating();
  }, [taskRunning, latestTaskVersionId, updateLinsight, stopGenerating]);

  return {
    t,
    conversationId,
    composerIdentity,
    inputText,
    setInputText,
    taskMode,
    bsConfig,
    chatModel,
    searchType,
    setSearchType,
    landingHasSelection,
    setLandingHasSelection,
    selectedOrgKbs,
    knowledgeAccessMessage,
    setSelectedOrgKbs,
    messages,
    activeConvoId,
    chatTitle,
    isLoading,
    historyError,
    isClearing,
    retryHistory,
    isStreaming,
    isParsingMedia,
    stopGenerating,
    regenerate,
    selectionState,
    isH5,
    chatContainerRef,
    isCompactLayout,
    isPhoneViewport,
    exportSheetOpen,
    setExportSheetOpen,
    importModalOpen,
    setImportModalOpen,
    handleImportSelect,
    canUseTaskMode,
    inviteQuotaBar,
    inviteQuotaDialog,
    handleSend,
    isNew,
    hasMessages,
    activeCitationMessageId,
    citationPanelElement,
    onOpenCitationPanel,
    closeCitationPanel,
    latestTaskVersionId,
    handleModelChange,
    handleModelAutoChange,
    attachmentAsk,
    retireAttachmentAsk,
    isTextAskPending,
    handleToggleTaskMode,
    taskArtifacts,
    chatAttachments,
    dockedCardRef,
    compareFreeze,
    fsMounted,
    setFsMounted,
    fsExpanded,
    fsBox,
    taskLinsight,
    taskWorkspaceFiles,
    reportTaskTurnLoadFailed,
    taskWorkspaceLoadState,
    taskRunning,
    awaitingUserInput,
    handleStop,
    id,
    shareToken,
    taskVersionIds,
    user,
    setChatModel,
    modelMode,
    adminDefaultModelId,
    taskConversationModelId,
    location,
    setTaskMode,
    keepTaskModeOnRewriteRef,
    userToggledRef,
    lastConversationIdRef,
    isTaskConversation,
  };
}

export type ChatViewModel = ReturnType<typeof useChatView>;

export function ChatView(props: ChatViewProps) {
  const t = useLocalize();
  const { showToast } = useToastContext();
  const model = useChatView(props, t, showToast);
  return <ChatSurfacePresentation model={model} />;
}

export default memo(ChatView);
