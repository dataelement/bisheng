import { useQuery, useQueryClient } from '@tanstack/react-query';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { getRecommendedAppsApi } from '~/api/apps';
import { writeAppChatOrigin, writeAppChatReturnTo } from '~/pages/appChat/appChatOrigin';
import AiChatInput from '~/components/Chat/AiChatInput';
import AiChatMessages from '~/components/Chat/AiChatMessages';
import { PinnedTaskPanel } from '~/components/Linsight/Execution/PinnedTaskPanel';
import { WorkspacePanel } from '~/components/Linsight/Artifacts/WorkspacePanel';
import { useWorkspacePanel } from '~/components/Linsight/Artifacts/useWorkspacePanel';
import { type ArtifactFile, toUploadedArtifacts } from '~/components/Linsight/Artifacts/artifactUtils';
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { userStopLinsightEvent } from '~/api/linsight';
import { SopStatus } from '~/store/linsight';
import { useCitationReferencePanel } from '~/components/Chat/Messages/Content/useCitationReferencePanel';
import { Spinner } from '~/components/svg';
import { useAuthContext } from '~/hooks/AuthContext';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import useAiChat from '~/hooks/useAiChat';
import useChatModelMemo from '~/hooks/useChatModelMemo';
import useLocalize from '~/hooks/useLocalize';
import store from '~/store';
import { addConversation, cn, generateUUID } from '~/utils';
import { Card, CardContent } from '../ui/Card';
import Landing from './Landing';
import Presentation from './Presentation';
import { ConversationData, QueryKeys } from '~/types/chat';
import AppAvator from '../Avator';
import {
  importMessagesToKnowledgeApi,
  listUploadableSpacesApi,
} from '~/api/messageExport';
import { translateApiErrorMessage } from '~/api/request';
import {
  ExportFormatSheet,
  MessageSelectionToolbar,
} from '~/components/Chat/MessageSelection';
import {
  useExitSelectionOnChatChange,
  useMessageSelection,
} from '~/hooks/useMessageSelection';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import { useToastContext } from '~/Providers';
import { NotificationSeverity } from '~/common';
import {
  AddToKnowledgeModal,
  type AddToKnowledgeSelection,
} from '~/pages/Subscription/Article/AddToKnowledgeModal';

const ChatView = ({ id = '', index = 0, shareToken = '' }: { id?: string, index?: number, shareToken?: string }) => {
  const t = useLocalize();
  const { conversationId: cid } = useParams();
  const location = useLocation();
  const conversationId = (cid ?? id) || 'new';

  const [inputText, setInputText] = useState('');

  // F035: task mode is a LOCAL toggle on the daily welcome page — no route jump.
  // The route stays `/c`; only submitting in task mode navigates to /linsight.
  // Initial value comes from nav state so the sidebar "新建任务" entry can land
  // here already in task mode (see Nav/NewChat handleNewTask).
  const [taskMode, setTaskMode] = useState<boolean>(
    !!(location.state as any)?.taskMode,
  );

  const { data: bsConfig } = useGetBsConfig();
  const { user } = useAuthContext();
  const [chatModel, setChatModel] = useRecoilState(store.chatModel);
  const [selectedOrgKbs, setSelectedOrgKbs] = useRecoilState(store.selectedOrgKbs);
  const [selectedAgentTools, setSelectedAgentTools] = useRecoilState(store.selectedAgentTools);
  const [agentToolsInitialized, setAgentToolsInitialized] = useRecoilState(store.agentToolsInitialized);
  const [searchType, setSearchType] = useRecoilState(store.searchType);

  // v2.5 interaction memory — per-user localStorage snapshots for the input
  // bar. The model selection is shared across chat surfaces (ChatView and
  // AiAssistantPanel), so it lives in useChatModelMemo. KB / tools are
  // ChatView-only and handled in the effect below. Rules:
  //  - KB space: default empty; remember user toggles
  //  - org KB: default per bsConfig.orgKbs[].default_checked; remember toggles
  //  - tools: default per bsConfig.tools[].default_checked; remember toggles
  useChatModelMemo(user, bsConfig as any);

  const memoReadyRef = useRef(false);
  useEffect(() => {
    if (!bsConfig || !user?.id) return;
    if (memoReadyRef.current) return;
    const prefix = `bs:${user.id}:`;

    // Org KBs + knowledge spaces (unified selectedOrgKbs atom).
    // Priority: any localStorage entry (including empty) wins so the user's
    // explicit clear is preserved across refresh; admin-configured
    // default_checked only applies on first session (key absent).
    // When org-KB is disabled by admin, keep knowledge-space selections and
    // only drop org KB entries.
    try {
      const raw = localStorage.getItem(`${prefix}selectedOrgKbs`);
      let saved: any[] | null = null;
      if (raw !== null) {
        try {
          const v = JSON.parse(raw);
          if (Array.isArray(v)) saved = v;
        } catch { /* ignore parse errors */ }
      }

      const orgKbDisabled = (bsConfig as any)?.knowledgeBase?.enabled === false;
      if (saved !== null) {
        setSelectedOrgKbs(
          orgKbDisabled
            ? saved.filter((item: any) => item?.type !== 'org')
            : saved
        );
      } else {
        const defaults = orgKbDisabled
          ? []
          : ((bsConfig as any)?.orgKbs || [])
            .filter((k: any) => k.default_checked)
            .map((k: any) => ({ id: String(k.id), name: k.name, type: 'org' }));
        setSelectedOrgKbs(defaults);
      }
    } catch { /* ignore */ }

    // Agent tool groups (parent-level). Same priority rule: any localStorage
    // entry (including empty) is treated as the user's choice; admin
    // default_checked only seeds the first session via AgentToolSelector
    // when no key exists yet.
    try {
      const raw = localStorage.getItem(`${prefix}selectedAgentTools`);
      let saved: any[] | null = null;
      if (raw !== null) {
        try {
          const v = JSON.parse(raw);
          if (Array.isArray(v)) saved = v;
        } catch { /* ignore parse errors */ }
      }
      if (saved !== null) {
        setSelectedAgentTools(saved);
        setAgentToolsInitialized(true);
      }
      // else: key absent → leave initialized=false so AgentToolSelector
      // applies admin defaults on first session.
    } catch { /* ignore */ }

    // Web search toggle. ChatForm clears searchType on conversation change,
    // but its effect runs before this one (children commit first), so the
    // hydrated value wins on initial mount and survives refresh / new tab.
    try {
      const saved = localStorage.getItem(`${prefix}searchType`);
      if (saved !== null) setSearchType(saved);
    } catch { /* ignore */ }

    memoReadyRef.current = true;
  }, [bsConfig, user?.id, setSelectedOrgKbs, setSelectedAgentTools, setAgentToolsInitialized, setSearchType]);


  // Persist on change (after initial hydrate completes).
  useEffect(() => {
    if (!memoReadyRef.current || !user?.id) return;
    localStorage.setItem(`bs:${user.id}:selectedOrgKbs`, JSON.stringify(selectedOrgKbs));
  }, [selectedOrgKbs, user?.id]);

  useEffect(() => {
    if (!memoReadyRef.current || !user?.id || !agentToolsInitialized) return;
    localStorage.setItem(`bs:${user.id}:selectedAgentTools`, JSON.stringify(selectedAgentTools));
  }, [selectedAgentTools, user?.id, agentToolsInitialized]);

  useEffect(() => {
    if (!memoReadyRef.current || !user?.id) return;
    localStorage.setItem(`bs:${user.id}:searchType`, searchType ?? '');
  }, [searchType, user?.id]);

  // Core chat state — replaces old ChatContext + useSSE + useChatHelpers
  const {
    messages,
    conversationId: activeConvoId,
    title: chatTitle,
    isLoading,
    isStreaming,
    sendMessage,
    stopGenerating,
    regenerate,
  } = useAiChat(conversationId, false, shareToken);

  // ── F028: workstation conversation export / import-to-knowledge ──
  // Auto-exit selection mode whenever the user switches to another chat.
  useExitSelectionOnChatChange(activeConvoId);
  const { state: selectionState, getSelectedIds, exitSelectionMode } =
    useMessageSelection();
  const isH5 = usePrefersMobileLayout();
  const { showToast } = useToastContext();
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
            t('workstation.messageExport.importSuccess') +
            (resp.dup_renamed ? ` (${resp.target_filename})` : ''),
          severity: NotificationSeverity.SUCCESS,
        });
        setImportModalOpen(false);
        exitSelectionMode();
      } catch (e: any) {
        // Prefer the backend business message (e.g. 12065 知识空间不存在 /
        // 12066 文件夹不存在 / 12067 暂无权限) so the user sees the real reason
        // instead of a generic failure — and never a false "success".
        showToast({
          message:
            translateApiErrorMessage({ status_code: e?.status_code, status_message: e?.status_message })
            || t('workstation.messageExport.renderFailed'),
          severity: NotificationSeverity.ERROR,
        });
      }
    },
    [activeConvoId, messages, getSelectedIds, showToast, t, exitSelectionMode],
  );

  const navigate = useNavigate();

  // F035: distinguishes the post-submit URL self-rewrite (same conversation
  // just got its real id — keep the composing mode) from a genuine navigation
  // to a different existing conversation (drop task mode). Set right before the
  // self-rewrite navigate below, consumed by the reset effect it triggers.
  const keepTaskModeOnRewriteRef = useRef(false);

  // F035: sync the local task-mode toggle to navigation. ChatView is NOT
  // remounted across `/c/:id` param changes (same route element), so the
  // useState initializer above only runs on first mount. This effect picks up
  // subsequent navigations:
  //  - sidebar "新建任务" lands on /c/new with state.taskMode=true → enter task mode.
  //  - the first submit on /c/new self-rewrites the URL to the real id; that is
  //    the SAME conversation, so the user's chosen mode is preserved (they can
  //    keep composing task turns, or toggle off manually).
  //  - any OTHER navigation to an existing conversation (id !== 'new') leaves
  //    task mode (you switched to viewing a daily chat, not composing a task).
  // location.key changes on every navigation so re-entering /c/new with the
  // same state still re-triggers.
  useEffect(() => {
    if (conversationId !== 'new') {
      // Post-submit self-rewrite: keep whatever mode the user is composing in.
      if (keepTaskModeOnRewriteRef.current) {
        keepTaskModeOnRewriteRef.current = false;
        return;
      }
      setTaskMode(false);
      return;
    }
    // On /c/new the mode is driven solely by the nav state: "新建任务" carries
    // state.taskMode=true, "新建对话" carries none. Set explicitly both ways so
    // switching from task → chat (or chat → task) actually flips the toggle
    // instead of leaving a stale mode behind.
    setTaskMode(!!(location.state as any)?.taskMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key, conversationId]);

  // Sync URL: ONLY when we were on /new and the hook just assigned a real ID.
  // Do NOT navigate if the user is clicking around in the sidebar (that changes
  // conversationId from params which should NOT be overridden by stale activeConvoId).
  useEffect(() => {
    if (
      conversationId === 'new' &&
      activeConvoId &&
      activeConvoId !== 'new'
    ) {
      // Flag the rewrite so the reset effect above preserves the current mode.
      keepTaskModeOnRewriteRef.current = true;
      navigate(`/c/${activeConvoId}`, { replace: true });
    }
  }, [activeConvoId]); // intentionally ONLY on activeConvoId — don't add navigate/conversationId

  const chatContainerRef = useRef<HTMLDivElement>(null);

  // Landing layout: measure the welcome+input block via callback ref so the
  // recommended-apps section can sit exactly 40px below it while the block
  // itself stays pinned at viewport vertical center via absolute positioning.
  // A callback ref re-attaches the ResizeObserver whenever the landing branch
  // is (re)mounted, which a useEffect with stale deps would miss.
  const landingResizeObserverRef = useRef<ResizeObserver | null>(null);
  const [landingBlockHeight, setLandingBlockHeight] = useState(0);
  const landingBlockRef = useCallback((el: HTMLDivElement | null) => {
    if (landingResizeObserverRef.current) {
      landingResizeObserverRef.current.disconnect();
      landingResizeObserverRef.current = null;
    }
    if (!el) return;
    const update = () => setLandingBlockHeight(el.offsetHeight);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    landingResizeObserverRef.current = ro;
  }, []);

  // F035: task mode is a ROLE permission. The backend folds each role's
  // menu_ids into web_menu → client `user.plugins`; `linsight_task_mode` is the
  // workbench-home sub-capability toggled per role in the admin console. When
  // the current user's role lacks it, hide the input's task-mode entry + skill
  // submenu (the sidebar "新建任务" button gates on the same key in Nav/NewChat).
  // plugins absent / non-array → allow (matches the NewChat default, and keeps
  // super-admin/dept-admin — who always carry the key — unaffected).
  const canUseTaskMode = useMemo(() => {
    const plugins = (user as any)?.plugins;
    return Array.isArray(plugins) ? plugins.includes('linsight_task_mode') : true;
  }, [user]);

  const handleSend = useCallback((text: string, files?: any[] | null) => {
    // F035 Track J (TJ-6): both modes go through the SAME unified entry now.
    // Task mode is just a per-turn flag — no /linsight navigation, no separate
    // submission pipeline. The turn stays in this daily conversation; the
    // backend hands off the linsight SV and the inline task bubble renders it.
    //
    // The unified entry now threads question + knowledge-base selection +
    // tools + uploaded files (backend _to_linsight_submit maps them onto the
    // linsight submit schema; daily-bucket files are parsed on-the-fly into the
    // task workspace). Skills are still resolved separately.
    if (taskMode && canUseTaskMode) {
      const trimmed = text.trim();
      if (!trimmed && !(files || []).length) return;
      sendMessage(trimmed, files, { taskMode: true });
      setInputText('');
      return;
    }

    sendMessage(text, files);
    setInputText('');
  }, [taskMode, canUseTaskMode, sendMessage]);

  const isNew = conversationId === 'new';
  const hasMessages = messages.length > 0;
  const { activeCitationMessageId, citationPanelElement, onOpenCitationPanel } = useCitationReferencePanel({ hasMessages });

  // F035: the task checklist is pinned above the input (Figma 12221-39902 /
  // 12221-40080) for the conversation's latest task turn — it tracks that turn's
  // execution detail from the linsight store rather than scrolling away in the
  // message stream.
  const latestTaskVersionId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i] as any;
      if (m?.category === 'task' && m?.linsightSessionVersionId) {
        return m.linsightSessionVersionId as string;
      }
    }
    return '';
  }, [messages]);

  // F035: workspace drawer for the chat-embedded task mode. Lifted to ChatView
  // (the task turn renders inline per message, but the entry button lives in the
  // shared header) and bound to the LATEST task turn. Shows uploaded sources +
  // generated deliverables. The drawer only opens on the header button — no
  // auto-expand (the entry icon appearing is enough).
  const { getLinsight, updateLinsight } = useLinsightManager();
  const taskArtifacts = useWorkspacePanel();

  // F035: enter/exit animation for the fullscreen workspace overlay. The overlay
  // is a separate instance from the docked panel (PreviewBody isn't cached, so we
  // never mount both at once). `fsMounted` keeps it in the DOM across the collapse
  // transition; `fsExpanded` drives the scale/opacity. Entering: mount collapsed,
  // then expand on the next frame so the transition runs. Exiting: collapse, then
  // unmount on transitionEnd.
  const [fsMounted, setFsMounted] = useState(false);
  const [fsExpanded, setFsExpanded] = useState(false);
  useEffect(() => {
    if (taskArtifacts.fullscreen) {
      setFsMounted(true);
      // Double rAF: let the collapsed state paint before flipping to expanded,
      // otherwise React can batch both and the enter transition is skipped.
      let r2 = 0;
      const r1 = requestAnimationFrame(() => {
        r2 = requestAnimationFrame(() => setFsExpanded(true));
      });
      return () => {
        cancelAnimationFrame(r1);
        cancelAnimationFrame(r2);
      };
    }
    setFsExpanded(false);
    return undefined;
  }, [taskArtifacts.fullscreen]);

  const taskLinsight = latestTaskVersionId ? getLinsight(latestTaskVersionId) : null;
  const taskWorkspaceFiles = useMemo(() => {
    const uploaded = toUploadedArtifacts(taskLinsight?.files as any[]);
    const generated = (taskLinsight?.file_list as ArtifactFile[]) || [];
    return [...uploaded, ...generated];
  }, [taskLinsight?.files, taskLinsight?.file_list]);

  // F035: while the latest task round is in a non-terminal state (generating /
  // running / queued), the input stays editable but the send button is disabled
  // — the next round can only be submitted after the current one finishes.
  const taskRunning = useMemo(() => {
    const status = (taskLinsight as any)?.status;
    return (
      status === SopStatus.NotStarted ||
      status === SopStatus.SopGenerating ||
      status === SopStatus.SopGenerated ||
      status === SopStatus.Running
    );
  }, [taskLinsight]);

  // Stop button handler. A task round runs via the linsight worker/WS, normally
  // AFTER the handoff SSE stream closed — route the stop to terminate-execute.
  const handleStop = useCallback(() => {
    if (taskRunning && latestTaskVersionId) {
      userStopLinsightEvent(latestTaskVersionId).catch(() => { /* best-effort: WS task_terminated reconciles */ });
      updateLinsight(latestTaskVersionId, (prev) => ({
        ...prev,
        status: SopStatus.Stoped,
        tasks: (prev.tasks || []).map((tk: any) => ({
          ...tk,
          status: tk.status === 'in_progress' ? 'terminated' : tk.status,
          children: tk.children
            ? tk.children.map((c: any) => ({ ...c, status: c.status === 'in_progress' ? 'terminated' : c.status }))
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

  return (
    <Presentation isLingsi={false}>
      <div className={cn('h-full')}>
        <div
          ref={chatContainerRef}
          className={cn("relative z-10 h-full noscrollbar", !hasMessages && "overflow-y-auto")}
        >
          {/* Layout: treat "loading an existing conversation" the same as
              "has messages" so the input stays pinned to the bottom during
              sidebar navigation (otherwise the centered welcome-page layout
              briefly floats the input up before messages arrive). */}
          {(() => {
            const loadingExistingConvo = isLoading && conversationId !== 'new';
            // Keep input pinned to bottom as soon as a send starts (before first token lands),
            // otherwise mobile can briefly fall back to the centered landing layout.
            // An EXISTING conversation (id !== 'new') always uses the detail layout,
            // even with zero messages — opening an empty conversation must show the
            // conversation view, not the welcome/landing page (landing is /c/new only).
            const useMessagesLayout = hasMessages || loadingExistingConvo || isStreaming || !isNew;
            return (
              <div className={cn(
                'flex flex-col relative',
                useMessagesLayout ? 'h-full' : ''
              )}>
                {/* Content area: Split into Chat Main and Citation Sidebar */}
                {isLoading && conversationId !== 'new' ? (
                  <div className="flex h-screen items-center justify-center">
                    <Spinner className="opacity-0" />
                  </div>
                ) : (hasMessages || !isNew) ? (
                  <div className="flex min-h-0 flex-1 overflow-hidden">
                    {/* Left: Chat Main (Messages + Input). */}
                    <div className="relative flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden">
                      <div className="relative flex min-h-0 flex-1 overflow-hidden">
                        <AiChatMessages
                          messages={messages}
                          conversationId={activeConvoId}
                          title={chatTitle}
                          isLoading={false}
                          isStreaming={isStreaming}
                          shareToken={shareToken}
                          knowledgeChatLayout
                          contentWidthClassName="w-full max-w-[800px] mx-auto px-3 touch-mobile:max-w-full"
                          onRegenerate={regenerate}
                          onOpenCitationPanel={onOpenCitationPanel}
                          activeCitationMessageId={activeCitationMessageId}
                          onOpenWorkspace={taskArtifacts.openWorkspace}
                          // Show the workspace entry whenever this is a task
                          // conversation (regardless of whether files exist yet);
                          // it's hidden only while the panel itself is open.
                          hasWorkspaceFiles={!!latestTaskVersionId}
                          workspaceOpen={taskArtifacts.open}
                          onPreviewFile={taskArtifacts.openPreview}
                          hideEmptyState
                          flatMode
                        />
                        {/* Soft translucent fade so the scrolling step flow
                            dissolves into the pinned task panel / input instead of
                            ending on a hard cut. */}
                        <div
                          aria-hidden
                          className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-12 bg-gradient-to-t from-white to-white/0"
                        />
                      </div>

                      {/* Input area — moved inside the left column to be independent of sidebar.
                          When F028 selection mode is active, the input is replaced by the
                          selection toolbar at 100% width. */}
                      {!shareToken && (
                        activeConvoId && selectionState.active && selectionState.chatId === activeConvoId ? (
                          <div className="w-full max-w-[800px] mx-auto touch-mobile:max-w-full py-1.5 shrink-0">
                            <MessageSelectionToolbar
                              chatId={activeConvoId}
                              messages={messages}
                              onExportToLocal={isH5 ? () => setExportSheetOpen(true) : undefined}
                              onImportToKnowledge={() => setImportModalOpen(true)}
                            />
                          </div>
                        ) : (
                          <div className="w-full max-w-[800px] mx-auto px-3 touch-mobile:max-w-full shrink-0 pb-3">
                            {latestTaskVersionId && <PinnedTaskPanel versionId={latestTaskVersionId} />}
                            <AiChatInput
                              disabled={!bsConfig?.models?.length || !!shareToken}
                              sendDisabled={taskRunning}
                              isStreaming={isStreaming}
                              taskRunning={taskRunning}
                              features={{ taskModeEntry: canUseTaskMode, taskMode: (taskMode || taskRunning) && canUseTaskMode }}
                              onToggleTaskMode={() => setTaskMode((v) => !v)}
                              placeholder={taskMode
                                ? ((bsConfig as any)?.linsightConfig?.input_placeholder || t('com_linsight_input_placeholder'))
                                : undefined}
                              onScrollToBottom={() => { }}
                              modelOptions={bsConfig?.models}
                              modelValue={chatModel.id}
                              onModelChange={(val) => {
                                const model = bsConfig?.models?.find((m) => m.id === val);
                                setChatModel({
                                  id: Number(val),
                                  name: model?.displayName || '',
                                });
                              }}
                              onSend={handleSend}
                              onStop={handleStop}
                              value={inputText}
                              onChange={setInputText}
                              bsConfig={bsConfig}
                              selectedOrgKbs={selectedOrgKbs}
                              onSelectedOrgKbsChange={setSelectedOrgKbs}
                              searchType={searchType}
                              onSearchTypeChange={setSearchType}
                            />
                          </div>
                        )
                      )}
                    </div>

                    {/* F035: inline workspace panel docked to the right of the chat
                        main for the latest task turn. Opens from the header entry
                        button; the file preview renders in place. Fullscreen is a
                        separate overlay (below) covering the whole route viewport.

                        Kept mounted whenever a task turn exists (gated only on
                        !fullscreen) so open/close animates the wrapper's width +
                        opacity instead of hard mount/unmount. Width uses an inline
                        clamp() (not min/max-w classes) so it interpolates smoothly
                        0px → 46% — min-width doesn't transition and would otherwise
                        snap to 440px on the first frame. The inner box keeps a
                        min-width so the panel content slides/clips rather than
                        reflowing while it collapses. */}
                    {latestTaskVersionId && !taskArtifacts.fullscreen && (
                      <div
                        className={cn(
                          'min-h-0 shrink-0 overflow-hidden transition-[width,opacity,padding] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]',
                          taskArtifacts.open ? 'p-1 opacity-100' : 'pointer-events-none p-0 opacity-0',
                        )}
                        style={{ width: taskArtifacts.open ? 'clamp(440px, 46%, 720px)' : '0px' }}
                      >
                        <div className="h-full min-w-[420px]">
                          <WorkspacePanel
                            files={taskWorkspaceFiles}
                            versionId={latestTaskVersionId}
                            previewFile={taskArtifacts.previewFile}
                            fullscreen={false}
                            onPreview={taskArtifacts.openPreview}
                            onBack={taskArtifacts.backToList}
                            onClose={taskArtifacts.closeWorkspace}
                            onToggleFullscreen={taskArtifacts.toggleFullscreen}
                          />
                        </div>
                      </div>
                    )}

                    {citationPanelElement}
                  </div>
                ) : (
                  /* Landing page branch — welcome + input are pinned to viewport
                     vertical center via absolute positioning (top:50% + translateY).
                     Recommended apps sit exactly 40px below the input by using
                     `paddingTop: calc(50vh + landingHalfHeight + 40px)`, where
                     `landingBlockHeight` is measured live with a ResizeObserver.
                     When total content exceeds viewport, the parent's
                     overflow-y-auto handles scrolling — the centered block scrolls
                     up with the document as expected. */
                  <div className="relative min-h-full">
                    {/* Centered: welcome message + input. `top: 50vh` (viewport
                        height), NOT `top: 50%` — the parent's effective height
                        gets stretched by the apps' paddingTop below, so a
                        percentage would resolve to a non-viewport midpoint. */}
                    <div
                      ref={landingBlockRef}
                      className="absolute inset-x-0 top-[45vh] -translate-y-1/2"
                    >
                      {/* F035 Track H (P5): daily/task mode switch removed —
                          task mode is reached via the sidebar "new task" entry
                          and the input-bar task-mode button. */}
                      <Landing isNew={isNew} />

                      {/* Input area for landing page */}
                      {!shareToken && (
                        <div className="w-full max-w-[800px] mx-auto px-3 mt-6 touch-mobile:mt-2 touch-mobile:max-w-full pb-3">
                          <AiChatInput
                            disabled={!bsConfig?.models?.length || !!shareToken}
                            sendDisabled={taskRunning}
                            isStreaming={isStreaming}
                            features={{ taskModeEntry: canUseTaskMode, taskMode: taskMode && canUseTaskMode }}
                            onToggleTaskMode={() => setTaskMode((v) => !v)}
                            placeholder={taskMode
                              ? ((bsConfig as any)?.linsightConfig?.input_placeholder || t('com_linsight_input_placeholder'))
                              : undefined}
                            onScrollToBottom={() => { }}
                            modelOptions={bsConfig?.models}
                            modelValue={chatModel.id}
                            onModelChange={(val) => {
                              const model = bsConfig?.models?.find((m) => m.id === val);
                              setChatModel({
                                id: Number(val),
                                name: model?.displayName || '',
                              });
                            }}
                            onSend={handleSend}
                            onStop={stopGenerating}
                            value={inputText}
                            onChange={setInputText}
                            bsConfig={bsConfig}
                            selectedOrgKbs={selectedOrgKbs}
                            onSelectedOrgKbsChange={setSelectedOrgKbs}
                            searchType={searchType}
                            onSearchTypeChange={setSearchType}
                          />
                        </div>
                      )}
                    </div>

                    {/* Recommended apps: 40px below the centered block. The
                        paddingTop pushes apps to (viewport midpoint) + (landing
                        half-height) + 40px = (landing block bottom) + 40px. */}
                    <div
                      style={{
                        paddingTop: `calc(45vh + ${landingBlockHeight / 2 + 40}px)`,
                      }}
                    >
                      <DailyFeaturedApps t={t} />
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

          {/* F035: fullscreen workspace preview — overlays the whole route
              viewport (chatContainerRef is relative + un-clipped), flush to the
              edges with no padding. Covers the chat (incl. its header) but not the
              browser, so the global nav stays. Separate instance from the inline
              panel above (only one is ever mounted, so the preview never double
              fetches). Scale + opacity transition from the right (where the docked
              panel sits) so expanding/collapsing fullscreen animates smoothly
              instead of hard mount/unmount; unmounts on transitionEnd after the
              collapse so the exit plays too. */}
          {latestTaskVersionId && fsMounted && (
            <div
              className={cn(
                'absolute inset-0 z-50 origin-right bg-white transition-[transform,opacity] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]',
                fsExpanded ? 'scale-100 opacity-100' : 'scale-[0.96] opacity-0',
              )}
              onTransitionEnd={(e) => {
                // Unmount only after the collapse finishes (ignore the expand end
                // and bubbled child transitions).
                if (e.target === e.currentTarget && e.propertyName === 'transform' && !taskArtifacts.fullscreen) {
                  setFsMounted(false);
                }
              }}
            >
              <WorkspacePanel
                files={taskWorkspaceFiles}
                versionId={latestTaskVersionId}
                previewFile={taskArtifacts.previewFile}
                fullscreen={true}
                onPreview={taskArtifacts.openPreview}
                onBack={taskArtifacts.backToList}
                onClose={taskArtifacts.closeWorkspace}
                onToggleFullscreen={taskArtifacts.toggleFullscreen}
              />
            </div>
          )}
        </div>

        {/* F028: portal-style sheets/modals (the floating toolbar lives next to the input) */}
        {activeConvoId && selectionState.active && selectionState.chatId === activeConvoId && (
          <>
            <ExportFormatSheet
              open={exportSheetOpen}
              onOpenChange={setExportSheetOpen}
              chatId={activeConvoId}
              messages={messages}
            />
            <AddToKnowledgeModal
              open={importModalOpen}
              onOpenChange={setImportModalOpen}
              mode="channel_sync"
              dataSourceApi={listUploadableSpacesApi}
              onSyncSelect={handleImportSelect}
            />
          </>
        )}

      </div>
    </Presentation>
  );
};

const DailyFeaturedApps = ({ t }: { t: (k: string) => string }) => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { setConversation } = store.useCreateConversationAtom(0)
  const appFlowOriginKey = (flowId: string) => `app-flow-origin:${flowId}`;
  const appLastOriginKey = 'app-last-origin';

  const { data: dailyApps = [] } = useQuery<any[]>(
    ['recommendedApps'],
    () => getRecommendedAppsApi().then((res: any) => res?.data ?? []),
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false },
  )

  const handleCardClick = (agent: any) => {
    const _chatId = generateUUID(32)
    const flowId = agent.id
    const flowType = agent.flow_type || agent.type
    const homeReturnTo = '/c/new';
    writeAppChatOrigin(_chatId, 'home');
    writeAppChatReturnTo(_chatId, homeReturnTo);
    try {
      sessionStorage.setItem(`app-chat-entry:${_chatId}`, 'home')
      sessionStorage.setItem(appFlowOriginKey(String(flowId)), 'home')
      sessionStorage.setItem(appLastOriginKey, 'home')
    } catch {
      // ignore storage failures
    }
    queryClient.setQueryData<ConversationData>([QueryKeys.allConversations], (convoData) => {
      if (!convoData) return convoData;
      return addConversation(convoData, {
        conversationId: _chatId,
        createdAt: "",
        endpoint: null,
        endpointType: null,
        model: "",
        flowId,
        flowType,
        title: agent.name,
        tools: [],
        updatedAt: ""
      } as any);
    });
    setConversation((prevState: any) => ({ ...prevState, conversationId: _chatId }))
    navigate(`/app/${_chatId}/${flowId}/${flowType}?from=home-recommended&entry=home&returnTo=${encodeURIComponent(homeReturnTo)}`, {
      state: { appSurfaceReturn: homeReturnTo },
    })
  }
  const displayApps = dailyApps

  if (dailyApps.length === 0) return null


  return (
    <div className="relative z-10 w-full pb-24">
      <div className="flex justify-between items-center mb-3 text-sm text-gray-500 max-w-[800px] mx-auto px-4">
        <h2 className="text-sm text-gray-400">推荐应用</h2>
      </div>
      <div className="relative max-w-[800px] mx-auto px-4">
        <div className="pr-1">
          <div className="grid grid-cols-2 touch-desktop:grid-cols-4 gap-3 mb-3">
            {displayApps.map((appItem) => (
              <Card
                key={appItem.id}
                className="group flex flex-col py-0 rounded-[8px] shadow-[0_2px_4px_rgba(0,0,0,0.02)] border border-[#E5E6EB] overflow-hidden cursor-pointer hover:border-[#335cff] hover:shadow-[0_4px_14px_rgba(51,92,255,0.12)] transition-all duration-300 h-[142px] hover:-translate-y-1"
                style={{ background: 'linear-gradient(135deg, #f9fbfe 0%, #fff 50%, #f9fbfe 100%)' }}
                onClick={() => handleCardClick(appItem)}
              >
                <CardContent className="h-full p-2 flex flex-col relative w-full">
                  <div className="flex items-center gap-2.5 mb-2 shrink-0">
                    <AppAvator
                      id={appItem.name}
                      url={appItem.logo}
                      flowType={appItem.flow_type || appItem.type}
                      className={`size-[32px] min-w-[32px] !rounded-[8px]`}
                      iconClassName="w-5 h-5"
                    />
                    <div className="text-[15px] font-medium text-[#1D2129] line-clamp-1 break-all">{appItem.name}</div>
                  </div>
                  <div className="text-[13px] text-[#86909C] line-clamp-2 break-all font-normal leading-[1.5]">{appItem.description}</div>

                  <div className="mt-auto pt-2 relative h-[30px] shrink-0 w-full overflow-hidden">
                    <div className="absolute inset-x-0 bottom-0 top-1 flex gap-1.5 flex-wrap overflow-hidden opacity-100 fine-pointer:group-hover:opacity-0 transition-opacity duration-200 pointer-events-none coarse-pointer:opacity-0">
                      {appItem.tags && appItem.tags.map((tag: any) => (
                        <div
                          key={tag.id || tag.name || tag}
                          className="bg-[#F2F3F5] text-[#4E5969] text-[12px] px-2 py-[2px] rounded-[4px] font-normal whitespace-nowrap"
                        >
                          {tag.name || tag}
                        </div>
                      ))}
                    </div>
                    <div className="absolute inset-x-0 bottom-0 top-1 flex items-center justify-center bg-[#335cff] rounded-[6px] text-white text-[13px] font-medium opacity-0 fine-pointer:group-hover:opacity-100 transform translate-y-2 fine-pointer:group-hover:translate-y-0 transition-all duration-300 coarse-pointer:opacity-100 coarse-pointer:translate-y-0">
                      开始对话
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default memo(ChatView);
