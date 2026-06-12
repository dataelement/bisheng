import { useQuery, useQueryClient } from '@tanstack/react-query';
import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { getRecommendedAppsApi } from '~/api/apps';
import { writeAppChatOrigin, writeAppChatReturnTo } from '~/pages/appChat/appChatOrigin';
import AiChatInput from '~/components/Chat/AiChatInput';
import AiChatMessages from '~/components/Chat/AiChatMessages';
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

  // Sync URL: ONLY when we were on /new and the hook just assigned a real ID.
  // Do NOT navigate if the user is clicking around in the sidebar (that changes
  // conversationId from params which should NOT be overridden by stale activeConvoId).
  useEffect(() => {
    if (
      conversationId === 'new' &&
      activeConvoId &&
      activeConvoId !== 'new'
    ) {
      navigate(`/c/${activeConvoId}`, { replace: true });
    }
  }, [activeConvoId]); // intentionally ONLY on activeConvoId — don't add navigate/conversationId

  const chatContainerRef = useRef<HTMLDivElement>(null);

  const handleSend = useCallback((text: string, files?: any[] | null) => {
    sendMessage(text, files);
    setInputText('');
  }, [sendMessage]);

  const isNew = conversationId === 'new';
  const hasMessages = messages.length > 0;
  const { activeCitationMessageId, citationPanelElement, onOpenCitationPanel } = useCitationReferencePanel({ hasMessages });

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
            const useMessagesLayout = hasMessages || loadingExistingConvo || isStreaming;
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
                ) : hasMessages ? (
                  <div className="flex min-h-0 flex-1 overflow-hidden">
                    {/* Left: Chat Main (Messages + Input) */}
                    <div className="relative flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden">
                      <div className="flex min-h-0 flex-1 overflow-hidden">
                        <AiChatMessages
                          messages={messages}
                          conversationId={activeConvoId}
                          title={chatTitle}
                          isLoading={false}
                          isStreaming={isStreaming}
                          shareToken={shareToken}
                          knowledgeChatLayout
                          contentWidthClassName="w-full max-w-[800px] mx-auto px-4 touch-mobile:max-w-full"
                          onRegenerate={regenerate}
                          onOpenCitationPanel={onOpenCitationPanel}
                          activeCitationMessageId={activeCitationMessageId}
                          flatMode
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
                        <div className="w-full max-w-[800px] mx-auto px-3 touch-mobile:mt-10 touch-mobile:max-w-full shrink-0 py-3">
                          <AiChatInput
                            disabled={!bsConfig?.models?.length || !!shareToken}
                            isStreaming={isStreaming}
                            features={{ taskModeEntry: true }}
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
                        )
                      )}
                    </div>

                    {citationPanelElement}
                  </div>
                ) : (
                  /* Landing page branch — Landing+input are pinned at ~25vh
                     from the viewport top via padding-top (independent of how
                     tall DailyFeaturedApps below becomes), so the welcome
                     block stays in roughly the same screen position whether
                     apps are absent or fill multiple rows. Apps follow
                     directly after the input with only their own mt-4 gap. */
                  <div className="flex flex-col min-h-[calc(100vh-200px)] touch-mobile:min-h-[calc(100dvh-240px)] pt-[25vh] touch-mobile:pt-[20vh]">
                    <div className="shrink-0">
                      {/* F035 Track H (P5): the in-place lingsi mode is gone —
                          selecting the task tab now jumps to the dedicated
                          /linsight task-mode landing page. */}
                      <Landing
                        lingsi={false}
                        lingsiEntry={(bsConfig as any)?.linsightConfig?.linsight_entry ?? true}
                        setLingsi={(bl: boolean) => {
                          if (bl) navigate('/linsight/new');
                        }}
                        isNew={isNew}
                      />
                    </div>

                    {/* Input area for landing page */}
                    {!shareToken && (
                      <div className="w-full max-w-[800px] mx-auto px-3 touch-mobile:mt-10 touch-mobile:max-w-full shrink-0 py-3">
                        <AiChatInput
                          disabled={!bsConfig?.models?.length || !!shareToken}
                          isStreaming={isStreaming}
                          features={{ taskModeEntry: true }}
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
                    <DailyFeaturedApps t={t} />
                  </div>
                )}
              </div>
            );
          })()}
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
    <div className="relative z-10 w-full mt-4 pb-24">
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
