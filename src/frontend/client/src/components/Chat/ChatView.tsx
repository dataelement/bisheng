import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, MousePointerClick } from 'lucide-react';
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { getRecommendedAppsApi } from '~/api/apps';
import { getFeaturedCases } from '~/api/linsight';
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
import { Button } from '../ui';
import { Card, CardContent } from '../ui/Card';
import { sameSopLabelState } from './Input/SameSopSpan';
import InvitationCodeForm from './InviteCode';
import Landing from './Landing';
import LinsightChatInput from './LinsightChatInput';
import Presentation from './Presentation';
import { ConversationData, QueryKeys } from '~/types/chat';
import AppAvator from '../Avator';

const ChatView = ({ id = '', index = 0, shareToken = '' }: { id?: string, index?: number, shareToken?: string }) => {
  const t = useLocalize();
  const { conversationId: cid } = useParams();
  const conversationId = (cid ?? id) || 'new';

  const [showCode, setShowCode] = useState(false);
  const [isLingsi, setIsLingsi] = useState(false);
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
    // default_checked only applies on first session (key absent). When the
    // KB feature is disabled by admin, clear the state regardless.
    try {
      if ((bsConfig as any)?.knowledgeBase?.enabled === false) {
        setSelectedOrgKbs([]);
      } else {
        const raw = localStorage.getItem(`${prefix}selectedOrgKbs`);
        let saved: any[] | null = null;
        if (raw !== null) {
          try {
            const v = JSON.parse(raw);
            if (Array.isArray(v)) saved = v;
          } catch { /* ignore parse errors */ }
        }
        if (saved !== null) {
          setSelectedOrgKbs(saved);
        } else {
          const defaults = ((bsConfig as any)?.orgKbs || [])
            .filter((k: any) => k.default_checked)
            .map((k: any) => ({ id: String(k.id), name: k.name, type: 'org' }));
          setSelectedOrgKbs(defaults);
        }
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
    clearConversation,
    regenerate,
  } = useAiChat(conversationId, false, shareToken);

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

  // Reset lingsi mode when messages exist
  useEffect(() => {
    if (messages.length > 0) {
      setIsLingsi(false);
    }
  }, [messages.length]);

  // Lingsi mode cases scroll loading
  const casesRef = useRef(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  useEffect(() => {
    const handleScroll = async (e: Event) => {
      const target = e.target as HTMLDivElement;
      const { scrollTop, scrollHeight, clientHeight } = target;
      if (scrollTop + clientHeight >= scrollHeight - 10 && !isLoadingMore && casesRef.current) {
        setIsLoadingMore(true);
        try {
          const hasMore = await (casesRef.current as any).loadMore();
          if (!hasMore) {
            console.log('No more data to load');
          }
        } catch (error) {
          console.error('Error loading more data:', error);
        } finally {
          setIsLoadingMore(false);
        }
      }
    };

    const chatContainer = chatContainerRef.current;
    if (chatContainer) {
      chatContainer.addEventListener('scroll', handleScroll);
    }
    return () => {
      if (chatContainer) {
        chatContainer.removeEventListener('scroll', handleScroll);
      }
    };
  }, [isLoadingMore]);

  const handleSend = useCallback((text: string, files?: any[] | null) => {
    sendMessage(text, files);
    setInputText('');
  }, [sendMessage]);

  const isNew = conversationId === 'new';
  const hasMessages = messages.length > 0;
  const { activeCitationMessageId, citationPanelElement, onOpenCitationPanel } = useCitationReferencePanel({ hasMessages });

  return (
    <Presentation isLingsi={isLingsi}>
      <div className={cn('h-full')}>
        {/* Lingsi video background */}
        <video
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
          className={cn(
            'absolute size-full object-cover object-center',
            'transition-opacity duration-500 ease-out',
            isLingsi ? 'opacity-100' : 'opacity-0'
          )}
        >
          <source src={`${__APP_ENV__.BASE_URL}/assets/linsi-bg.mp4`} type="video/mp4" />
          <img src={`${__APP_ENV__.BASE_URL}/assets/lingsi-bg.png`} alt="" />
        </video>

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
            const useMessagesLayout = hasMessages || loadingExistingConvo;
            return (
              <div className={cn(
                showCode ? 'hidden' : 'flex flex-col relative',
                useMessagesLayout ? 'h-full' : 'h-[calc(100vh-200px)] touch-mobile:min-h-[calc(100dvh-240px)] touch-mobile:h-auto justify-center'
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

                      {/* Input area — moved inside the left column to be independent of sidebar */}
                      {!shareToken && (
                        <div className="w-full max-w-[800px] mx-auto px-3 touch-mobile:mt-10 touch-mobile:max-w-full shrink-0 py-3">
                          {isLingsi ? (
                            <LinsightChatInput
                              disabled={!!shareToken}
                              isStreaming={isStreaming}
                              isLingsi
                              onSend={handleSend}
                              onStop={stopGenerating}
                              onNewChat={() => {
                                setSelectedOrgKbs([]);
                                setSearchType('');
                                clearConversation();
                                navigate('/c/new');
                                document.getElementById('create-convo-btn')?.click();
                              }}
                              value={inputText}
                              onChange={setInputText}
                              bsConfig={bsConfig}
                              setShowCode={setShowCode}
                            />
                          ) : (
                            <AiChatInput
                              disabled={!bsConfig?.models?.length || !!shareToken}
                              isStreaming={isStreaming}
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
                          )}
                        </div>
                      )}
                    </div>

                    {citationPanelElement}
                  </div>
                ) : (
                  /* Landing page branch */
                  <div className="flex flex-col h-full">
                    <div className="flex-1 overflow-hidden flex flex-col justify-center">
                      <Landing
                        lingsi={isLingsi}
                        lingsiEntry={(bsConfig as any)?.linsightConfig?.linsight_entry ?? true}
                        setLingsi={setIsLingsi}
                        isNew={isNew}
                      />
                    </div>

                    {/* Input area for landing page */}
                    {!shareToken && (
                      <div className="w-full max-w-[800px] mx-auto px-3 touch-mobile:mt-10 touch-mobile:max-w-full shrink-0 py-3">
                        {isLingsi ? (
                          <LinsightChatInput
                            disabled={!!shareToken}
                            isStreaming={isStreaming}
                            isLingsi
                            onSend={handleSend}
                            onStop={stopGenerating}
                            onNewChat={() => {
                              setSelectedOrgKbs([]);
                              setSearchType('');
                              clearConversation();
                              navigate('/c/new');
                              document.getElementById('create-convo-btn')?.click();
                            }}
                            value={inputText}
                            onChange={setInputText}
                            bsConfig={bsConfig}
                            setShowCode={setShowCode}
                          />
                        ) : (
                          <AiChatInput
                            disabled={!bsConfig?.models?.length || !!shareToken}
                            isStreaming={isStreaming}
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
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })()}

          {/* Lingsi Cases */}
          <Cases ref={casesRef} t={t} isLingsi={isLingsi} setIsLingsi={setIsLingsi} />
          {/* Recommended apps — welcome page only. Also suppress while a
              sidebar-nav is loading the new conversation, otherwise the chips
              flicker into view for one frame before messages arrive. */}
          {!hasMessages && !(isLoading && conversationId !== 'new') && (
            <DailyFeaturedApps t={t} isLingsi={isLingsi} />
          )}
        </div>

        {/* Invitation Code */}
        <InvitationCodeForm showCode={showCode} setShowCode={setShowCode} />
      </div>
    </Presentation>
  );
};

const DailyFeaturedApps = ({ t, isLingsi }: { t: (k: string) => string; isLingsi: boolean }) => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { setConversation } = store.useCreateConversationAtom(0)
  const appFlowOriginKey = (flowId: string) => `app-flow-origin:${flowId}`;

  const { data: dailyApps = [] } = useQuery<any[]>(
    ['recommendedApps'],
    () => getRecommendedAppsApi().then((res: any) => res?.data ?? []),
    { enabled: !isLingsi, staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false },
  )

  const handleCardClick = (agent: any) => {
    const _chatId = generateUUID(32)
    const flowId = agent.id
    const flowType = agent.flow_type || agent.type
    try {
      sessionStorage.setItem(`app-chat-entry:${_chatId}`, 'home')
      sessionStorage.setItem(appFlowOriginKey(String(flowId)), 'home')
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
    navigate(`/app/${_chatId}/${flowId}/${flowType}?from=home-recommended&entry=home`)
  }
  const displayApps = dailyApps

  if (isLingsi || dailyApps.length === 0) return null


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


// ==================== Lingsi Cases Component (preserved as-is) ====================
const Cases = forwardRef(({ t, isLingsi, setIsLingsi }: any, ref) => {
  const [_, setSameSopLabel] = useRecoilState(sameSopLabelState);
  const [casesData, setCasesData] = useState<any[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);

  const queryParams = typeof window !== 'undefined' ? new URLSearchParams(location.search) : null;
  const sopid = queryParams?.get('sopid');
  const sopName = queryParams?.get('name');
  const sopSharePath = queryParams?.get('path');

  const handleCardClick = (sopId: string) => {
    window.open(`${__APP_ENV__.BASE_URL}/linsight/case/${sopId}`);
  };

  const loadMore = async (): Promise<boolean> => {
    if (!hasMore || isLoading) return false;

    setIsLoading(true);
    try {
      const nextPage = currentPage + 1;
      const res = await getFeaturedCases(nextPage);

      if (res.data.items.length > 0) {
        setCasesData((prev) => [...prev, ...res.data.items]);
        setCurrentPage(nextPage);
        setHasMore(res.data.items.length === 12);
        return true;
      } else {
        setHasMore(false);
        return false;
      }
    } catch (error) {
      console.error('Error loading more cases:', error);
      return false;
    } finally {
      setIsLoading(false);
    }
  };

  useImperativeHandle(ref, () => ({
    loadMore,
  }));

  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const res = await getFeaturedCases(1);
        setCasesData(res.data.items);
        setHasMore(res.data.items.length === 12);

        if (sopid) {
          const caseItem = res.data.items.find((item: any) => item.id === Number(sopid));
          if (caseItem) {
            setSameSopLabel({ ...caseItem });
            setIsLingsi(true);
          }
        } else if (sopName && sopSharePath) {
          setSameSopLabel({ id: '', name: decodeURIComponent(sopName), url: decodeURIComponent(sopSharePath) });
          setIsLingsi(true);
        }
      } catch (error) {
        console.error('Error loading initial cases:', error);
      }
    };

    loadInitialData();
  }, [sopid, setIsLingsi]);

  if (!isLingsi) return null;
  if (casesData.length === 0) return null;

  return (
    <div className="relative w-full mt-8 pb-20">
      <p className="text-sm text-center text-gray-400">{t('com_case_featured')}</p>
      <div className="flex flex-wrap pt-4 mx-auto gap-2 w-[782px]">
        {casesData.map((caseItem) => (
          <Card
            key={caseItem.id}
            className="w-[254px] py-0 rounded-2xl shadow-none hover:shadow-xl group relative overflow-hidden"
          >
            <CardContent className="flex flex-col justify-between h-[98px] p-4">
              <div className="text-sm font-medium text-gray-800 line-clamp-2">{caseItem.name}</div>
              <div className="absolute bottom-2 right-4 flex justify-end space-x-2 mt-2 opacity-0 translate-y-2 group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-300">
                <Button
                  variant="default"
                  className="bg-primary text-white rounded-full h-8 px-3 text-xs flex items-center space-x-0"
                  onClick={() => setSameSopLabel({ ...caseItem })}
                >
                  <MousePointerClick className="w-3.5 h-3.5" />
                  <span>{t('com_make_samestyle')}</span>
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  className="rounded-full w-8 h-8 p-0 text-xs flex items-center space-x-1 bg-transparent"
                  onClick={() => handleCardClick(caseItem.id.toString())}
                >
                  <ArrowRight className="w-3.5 h-3.5" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
});
