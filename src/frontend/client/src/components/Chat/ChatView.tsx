import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, MousePointerClick } from 'lucide-react';
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { getRecommendedAppsApi } from '~/api/apps';
import { getFeaturedCases } from '~/api/linsight';
import AiChatInput from '~/components/Chat/AiChatInput';
import AiChatMessages from '~/components/Chat/AiChatMessages';
import { Spinner } from '~/components/svg';
import { useAuthContext } from '~/hooks/AuthContext';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import useAiChat from '~/hooks/useAiChat';
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
  // bar (model, kb selection, tools). Rules:
  //  - model: default = latest backend model; if user-saved model was deleted,
  //    fall back to latest again
  //  - KB space: default empty; remember user toggles
  //  - org KB: default per bsConfig.orgKbs[].default_checked; remember toggles
  //  - tools: default per bsConfig.tools[].default_checked; remember toggles
  const memoReadyRef = useRef(false);
  useEffect(() => {
    if (!bsConfig || !user?.id) return;
    if (memoReadyRef.current) return;
    const prefix = `bs:${user.id}:`;

    // Model: stored id wins if still present; otherwise latest configured model.
    try {
      const savedModelId = localStorage.getItem(`${prefix}chatModel`);
      const models = (bsConfig as any)?.models || [];
      let target = savedModelId
        ? models.find((m: any) => String(m.id) === savedModelId)
        : null;
      if (!target && models.length) target = models[models.length - 1];
      if (target) {
        setChatModel({ id: Number(target.id), name: target.displayName || target.name });
      }
    } catch { /* ignore */ }

    // Org KBs + knowledge spaces (unified selectedOrgKbs atom).
    try {
      const raw = localStorage.getItem(`${prefix}selectedOrgKbs`);
      if (raw) {
        setSelectedOrgKbs(JSON.parse(raw));
      } else {
        const defaults = ((bsConfig as any)?.orgKbs || [])
          .filter((k: any) => k.default_checked)
          .map((k: any) => ({ id: String(k.id), name: k.name, type: 'org' }));
        setSelectedOrgKbs(defaults);
      }
    } catch { /* ignore */ }

    // Agent tool groups (parent-level). AgentToolSelector still seeds from
    // default_checked on first run; localStorage overrides that when present.
    try {
      const raw = localStorage.getItem(`${prefix}selectedAgentTools`);
      if (raw) {
        setSelectedAgentTools(JSON.parse(raw));
        setAgentToolsInitialized(true);
      }
    } catch { /* ignore */ }

    memoReadyRef.current = true;
  }, [bsConfig, user?.id, setChatModel, setSelectedOrgKbs, setSelectedAgentTools, setAgentToolsInitialized]);

  // Persist on change (after initial hydrate completes).
  useEffect(() => {
    if (!memoReadyRef.current || !user?.id || !chatModel.id) return;
    localStorage.setItem(`bs:${user.id}:chatModel`, String(chatModel.id));
  }, [chatModel.id, user?.id]);

  useEffect(() => {
    if (!memoReadyRef.current || !user?.id) return;
    localStorage.setItem(`bs:${user.id}:selectedOrgKbs`, JSON.stringify(selectedOrgKbs));
  }, [selectedOrgKbs, user?.id]);

  useEffect(() => {
    if (!memoReadyRef.current || !user?.id || !agentToolsInitialized) return;
    localStorage.setItem(`bs:${user.id}:selectedAgentTools`, JSON.stringify(selectedAgentTools));
  }, [selectedAgentTools, user?.id, agentToolsInitialized]);

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

        <div ref={chatContainerRef} className="relative z-10 h-full overflow-y-auto noscrollbar">
          <div className={cn(
            showCode ? 'hidden' : 'flex flex-col relative',
            hasMessages ? 'h-full' : 'h-[calc(100vh-200px)] max-[575px]:min-h-[calc(100dvh-240px)] max-[575px]:h-auto justify-center'
          )}>
            {/* Content area */}
            {isLoading && conversationId !== 'new' ? (
              <div className="flex h-screen items-center justify-center">
                <Spinner className="opacity-0" />
              </div>
            ) : hasMessages ? (
              /* Messages — using new AiChatMessages (v2.5: flat, no sibling tree) */
              <AiChatMessages
                messages={messages}
                conversationId={activeConvoId}
                title={chatTitle}
                isLoading={false}
                isStreaming={isStreaming}
                shareToken={shareToken}
                knowledgeChatLayout
                contentWidthClassName="max-w-[768px] mx-auto"
                onRegenerate={regenerate}
                flatMode
              />
            ) : (
              /* Landing page — preserved for welcome + Lingsi mode switch */
              <Landing
                lingsi={isLingsi}
                lingsiEntry={(bsConfig as any)?.linsightConfig?.linsight_entry || true}
                setLingsi={setIsLingsi}
                isNew={isNew}
              />
            )}

            {/* Input area — using new AiChatInput */}
            {!shareToken && <div className="w-full max-w-[768px] mx-auto max-[575px]:max-w-full max-[575px]:px-3 shrink-0">
              {isLingsi ?
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
                    // Navigate to /c/new to show Landing
                    navigate('/c/new');
                    // Trigger sidebar to sync
                    document.getElementById('create-convo-btn')?.click();
                  }}
                  value={inputText}
                  onChange={setInputText}
                  bsConfig={bsConfig}
                  setShowCode={setShowCode}
                />
                : <AiChatInput
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
                />}
            </div>}
          </div>

          {/* Lingsi Cases */}
          <Cases ref={casesRef} t={t} isLingsi={isLingsi} setIsLingsi={setIsLingsi} />
          <DailyFeaturedApps t={t} isLingsi={isLingsi} />
        </div>

        {/* Invitation Code */}
        <InvitationCodeForm showCode={showCode} setShowCode={setShowCode} />
      </div>
    </Presentation>
  );
};

// Icon background by flow type: 10=workflow(blue), 5=assistant(orange), 1=skill(black)
const getIconBgClass = (flowType: number) => {
  switch (Number(flowType)) {
    case 10:
      return "bg-primary"
    case 5:
      return "bg-orange-400"
    case 1:
      return "bg-black"
    default:
      return "bg-gray-100"
  }
}

const DailyFeaturedApps = ({ t, isLingsi }: { t: (k: string) => string; isLingsi: boolean }) => {
  const [expanded, setExpanded] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { setConversation } = store.useCreateConversationAtom(0)

  const { data: dailyApps = [] } = useQuery<any[]>(
    ['recommendedApps'],
    () => getRecommendedAppsApi().then((res: any) => res?.data ?? []),
    { enabled: !isLingsi, staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false },
  )

  const handleCardClick = (agent: any) => {
    const _chatId = generateUUID(32)
    const flowId = agent.id
    const flowType = agent.flow_type || agent.type
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
    navigate(`/chat/${_chatId}/${flowId}/${flowType}`)
  }

  if (isLingsi || dailyApps.length === 0) return null

  // Default show 8 apps (2x4), expanded show all (up to 16, 4x4)
  const displayApps = expanded ? dailyApps : dailyApps.slice(0, 8)
  const canExpand = dailyApps.length > 8

  return (
    <div className="relative w-full mt-1 md:mt-4 pb-24">
      <div className="flex justify-between items-center mb-3 text-sm text-gray-500 md:max-w-2xl xl:max-w-3xl mx-auto">
        <h2 className="text-sm text-gray-400">平台推荐应用</h2>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3 md:max-w-2xl xl:max-w-3xl mx-auto">
        {displayApps.map((appItem) => (
          <Card
            key={appItem.id}
            className="flex flex-col py-0 rounded-[6px] shadow-sm border border-[#ebecf0] bg-gradient-to-br from-[#F9FBFE] via-white to-[#F9FBFE] overflow-hidden cursor-pointer hover:border-[#335cff] hover:shadow-[0px_2px_8px_1px_rgba(117,145,212,0.12)] transition-all"
            onClick={() => handleCardClick(appItem)}
          >
            <CardContent className="h-full p-3 flex flex-col">
              <div className="flex items-center gap-2 mb-2">
                <AppAvator
                  id={appItem.name}
                  url={appItem.logo}
                  flowType={appItem.flow_type}
                  className={`size-5 min-w-5 p-0.5 rounded-md ${getIconBgClass(appItem.flow_type || appItem.type)}`}
                />
                <div className="text-sm font-medium text-gray-800 line-clamp-1 break-all">{appItem.name}</div>
              </div>
              <div className="text-xs text-gray-500 line-clamp-2 break-all font-light">{appItem.description}</div>
              {appItem.tags && appItem.tags.length > 0 && (
                <div className="flex gap-1 flex-wrap mt-auto pt-2">
                  {appItem.tags.map((tag) => (
                    <div
                      key={tag.id}
                      className="bg-[#F2F3F5] text-[#4E5969] text-xs px-2 py-0.5 rounded-[4px] font-normal"
                    >
                      {tag.name}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      {canExpand && (
        <div className="flex justify-center mt-2 pb-6">
          <Button
            variant="outline"
            className="rounded-full text-xs h-8 text-blue-500 border-blue-200 bg-white shadow-sm"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? '收起' : '展示更多'}
          </Button>
        </div>
      )}
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