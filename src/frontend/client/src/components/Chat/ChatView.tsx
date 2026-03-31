import { ArrowRight, MousePointerClick } from 'lucide-react';
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { getFeaturedCases } from '~/api/linsight';
import AiChatInput from '~/components/Chat/AiChatInput';
import AiChatMessages from '~/components/Chat/AiChatMessages';
import { Spinner } from '~/components/svg';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import useAiChat from '~/hooks/useAiChat';
import useLocalize from '~/hooks/useLocalize';
import store from '~/store';
import { cn } from '~/utils';
import { Button } from '../ui';
import { Card, CardContent } from '../ui/Card';
import { sameSopLabelState } from './Input/SameSopSpan';
import InvitationCodeForm from './InviteCode';
import Landing from './Landing';
import LinsightChatInput from './LinsightChatInput';
import Presentation from './Presentation';


const ChatView = ({ id = '', index = 0, shareToken = '' }: { id?: string, index?: number, shareToken?: string }) => {
  const t = useLocalize();
  const { conversationId: cid } = useParams();
  const conversationId = (cid ?? id) || 'new';

  const [showCode, setShowCode] = useState(false);
  const [isLingsi, setIsLingsi] = useState(false);
  const [inputText, setInputText] = useState('');

  const { data: bsConfig } = useGetBsConfig();
  const [chatModel, setChatModel] = useRecoilState(store.chatModel);
  const [selectedOrgKbs, setSelectedOrgKbs] = useRecoilState(store.selectedOrgKbs);
  const [searchType, setSearchType] = useRecoilState(store.searchType);

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
  } = useAiChat(conversationId);

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

  useEffect(() => {
    (window as any).isLinsight = isLingsi;
  }, [isLingsi]);

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
            hasMessages ? 'h-full' : 'h-[calc(100vh-200px)] justify-center'
          )}>
            {/* Content area */}
            {isLoading && conversationId !== 'new' ? (
              <div className="flex h-screen items-center justify-center">
                <Spinner className="opacity-0" />
              </div>
            ) : hasMessages ? (
              /* Messages — using new AiChatMessages */
              <AiChatMessages
                messages={messages}
                conversationId={activeConvoId}
                title={chatTitle}
                isLoading={false}
                isStreaming={isStreaming}
                shareToken={shareToken}
                onRegenerate={regenerate}
              />
            ) : (
              /* Landing page — preserved for welcome + Lingsi mode switch */
              <Landing
                lingsi={isLingsi}
                lingsiEntry={(bsConfig as any)?.linsightConfig?.linsight_entry}
                setLingsi={setIsLingsi}
                isNew={isNew}
              />
            )}

            {/* Input area — using new AiChatInput */}
            {!shareToken && <div className="w-full max-w-[768px] mx-auto">
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
        </div>

        {/* Invitation Code */}
        <InvitationCodeForm showCode={showCode} setShowCode={setShowCode} />
      </div>
    </Presentation>
  );
};

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