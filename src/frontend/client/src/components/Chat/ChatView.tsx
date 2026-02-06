import { ArrowRight, MousePointerClick } from 'lucide-react';
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { getFeaturedCases } from '~/api/linsight';
import type { ChatFormValues } from '~/common';
import { Spinner } from '~/components/svg';
import type { TMessage } from '~/data-provider/data-provider/src';
import { useGetMessagesByConvoId } from '~/data-provider/data-provider/src/react-query';
import { useAddedResponse, useChatHelpers, useSSE } from '~/hooks';
import useLocalize from '~/hooks/useLocalize';
import { AddedChatContext, ChatContext, ChatFormProvider, useFileMapContext } from '~/Providers';
import store from '~/store';
import { buildTree, cn } from '~/utils';
import { Button } from '../ui';
import { Card, CardContent } from '../ui/Card';
import HeaderTitle from './HeaderTitle';
import ChatForm from './Input/ChatForm';
import { sameSopLabelState } from './Input/SameSopSpan';
import InvitationCodeForm from './InviteCode';
import Landing from './Landing';
import MessagesView from './Messages/MessagesView';
import Presentation from './Presentation';
import { useGetBsConfig } from '~/data-provider';


const ChatView = ({ id = '', index = 0, shareToken = '' }: { id?: string, index?: number, shareToken?: string }) => {
  const t = useLocalize();
  const { conversationId: cid } = useParams();
  const conversationId = cid ?? id;
  const rootSubmission = useRecoilValue(store.submissionByIndex(index));
  const addedSubmission = useRecoilValue(store.submissionByIndex(index + 1));
  const [showCode, setShowCode] = useState(false);
  const [inputFloat, setInputFloat] = useState(false);
  const [inputWidth, setInputWidth] = useState(0); // To hold the calculated width

  const { data: bsConfig } = useGetBsConfig();
  const navigate = useNavigate();
  const fileMap = useFileMapContext();

  const { data: messagesTree = null, isLoading } = useGetMessagesByConvoId(conversationId ?? '', shareToken, {
    select: useCallback(
      (data: TMessage[]) => {
        // console.log('messagesTree :>> ', data);
        const dataTree = buildTree({ messages: data, fileMap });
        return dataTree?.length === 0 ? null : (dataTree ?? null);
      },
      [fileMap],
    ),
    enabled: !!fileMap,
  });

  const [isLingsi, setIsLingsi] = useState(false);
  useEffect(() => {
    window.isLinsight = isLingsi
  }, [isLingsi])
  const chatHelpers = useChatHelpers(index, conversationId, isLingsi);
  const addedChatHelpers = useAddedResponse({ rootIndex: index });

  useSSE(rootSubmission, chatHelpers, false);
  useSSE(addedSubmission, addedChatHelpers, true);

  const methods = useForm<ChatFormValues>({
    defaultValues: { text: '' },
  });

  // 提取title in messagesTree
  const conversation = useMemo(() => ({
    ...chatHelpers?.conversation,
    title: messagesTree?.[0]?.flow_name || '',
  }), [chatHelpers]);

  useEffect(() => {
    if (messagesTree && messagesTree.length !== 0) {
      setIsLingsi(false);
    }
  }, [messagesTree]);

  // Handle scroll event to trigger float input
  const chatContainerRef = useRef<HTMLDivElement>(null); // 创建 ref
  const casesRef = useRef(null)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  useEffect(() => {
    let hideLocal = 0
    const handleScroll = async (e: Event) => {
      const target = e.target as HTMLDivElement
      const scrollTop = target.scrollTop
      const floatPanne = document.getElementById("floatPanne")

      if (floatPanne) {
        const rect = floatPanne.getBoundingClientRect()
        if (rect.top <= 20) {
          setInputFloat(true)
          setInputWidth(rect.width)
          console.log("e :>> ")
          if (hideLocal === 0) {
            hideLocal = scrollTop
          }
        }
        if (hideLocal > 0 && scrollTop < hideLocal) {
          setInputFloat(false)
          hideLocal = 0
        }
      }

      const { scrollHeight, clientHeight } = target
      if (scrollTop + clientHeight >= scrollHeight - 10 && !isLoadingMore && casesRef.current) {
        setIsLoadingMore(true)
        try {
          const hasMore = await casesRef.current.loadMore()
          if (!hasMore) {
            console.log("No more data to load")
          }
        } catch (error) {
          console.error("Error loading more data:", error)
        } finally {
          setIsLoadingMore(false)
        }
      }
    }

    const chatContainer = chatContainerRef.current
    if (chatContainer) {
      chatContainer.addEventListener("scroll", handleScroll)
    }
    return () => {
      if (chatContainer) {
        chatContainer.removeEventListener("scroll", handleScroll)
      }
    }
  }, [isLoadingMore])

  const isNew = conversationId === 'new';
  let content: JSX.Element | null | undefined;

  if (isLoading && conversationId !== 'new') {
    content = (
      <div className="flex h-screen items-center justify-center">
        <Spinner className="opacity-0" />
      </div>
    );
  } else if (messagesTree && messagesTree.length !== 0) {
    content = <MessagesView readOnly={shareToken} messagesTree={messagesTree} Header={<HeaderTitle readOnly={shareToken} conversation={conversation} logo={null} />} />;
  } else {
    content = <Landing lingsi={isLingsi} lingsiEntry={bsConfig?.linsightConfig?.linsight_entry} setLingsi={setIsLingsi} isNew={isNew} />;
  }

  return (
    <ChatFormProvider {...methods}>
      <ChatContext.Provider value={chatHelpers}>
        <AddedChatContext.Provider value={addedChatHelpers}>
          <Presentation isLingsi={isLingsi}>
            <div className={cn(`h-full`)}>
              <video
                autoPlay
                loop
                muted
                playsInline
                preload="auto"
                className={cn(
                  "absolute size-full object-cover object-center",
                  "transition-opacity duration-500 ease-out",
                  isLingsi ? "opacity-100" : "opacity-0"
                )}
              >
                <source src={`${__APP_ENV__.BASE_URL}/assets/linsi-bg.mp4`} type="video/mp4" />
                <img src={`${__APP_ENV__.BASE_URL}/assets/lingsi-bg.png`} alt="" />
              </video>
              <div ref={chatContainerRef} className='relative z-10 h-full overflow-y-auto'>
                <div className={cn(showCode ? "hidden" : "flex flex-col justify-center relative",
                  messagesTree ? ' h-full' : 'h-[calc(100vh-200px)]'
                )}>
                  {content}
                  <div
                    id="floatPanne"
                    className={cn(
                      'w-full border-t-0 pl-0 pt-2 dark:border-white/20 md:w-[calc(100%-.5rem)] md:border-t-0 md:border-transparent md:pl-0 md:pt-0 md:dark:border-transparent',
                      inputFloat ? 'fixed top-0 z-10 bg-white pb-20 md:pt-5' : ''
                    )}
                    style={{ width: inputFloat ? `${inputWidth}px` : '100%' }} // Dynamically set width
                  >
                    <ChatForm isLingsi={isLingsi} setShowCode={setShowCode} index={index} readOnly={shareToken} />
                    {!inputFloat && <div className="h-[2vh]"></div>}
                  </div>
                </div>
                <Cases ref={casesRef} t={t} isLingsi={isLingsi} setIsLingsi={setIsLingsi} />
              </div>
              {/*   邀请码 */}
              <InvitationCodeForm showCode={showCode} setShowCode={setShowCode} />
            </div >
          </Presentation >
        </AddedChatContext.Provider >
      </ChatContext.Provider >
    </ChatFormProvider >
  );
};

export default memo(ChatView);


const Cases = forwardRef(({ t, isLingsi, setIsLingsi }, ref) => {
  const [_, setSameSopLabel] = useRecoilState(sameSopLabelState)
  const [casesData, setCasesData] = useState<any[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [isLoading, setIsLoading] = useState(false)

  const queryParams = typeof window !== "undefined" ? new URLSearchParams(location.search) : null
  const sopid = queryParams?.get("sopid")
  const sopName = queryParams?.get("name")
  const sopSharePath = queryParams?.get("path")

  const handleCardClick = (sopId: string) => {
    window.open(`${__APP_ENV__.BASE_URL}/linsight/case/${sopId}`)
  }

  const loadMore = async (): Promise<boolean> => {
    if (!hasMore || isLoading) return false

    setIsLoading(true)
    try {
      const nextPage = currentPage + 1
      const res = await getFeaturedCases(nextPage)

      if (res.data.items.length > 0) {
        setCasesData((prev) => [...prev, ...res.data.items]) // Prepend new items for upward scroll
        setCurrentPage(nextPage)
        setHasMore(res.data.items.length === 12)
        return true
      } else {
        setHasMore(false)
        return false
      }
    } catch (error) {
      console.error("Error loading more cases:", error)
      return false
    } finally {
      setIsLoading(false)
    }
  }

  useImperativeHandle(ref, () => ({
    loadMore,
  }))

  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const res = await getFeaturedCases(1)
        setCasesData(res.data.items)
        setHasMore(res.data.items.length === 12)

        // If sopid exists, find and set the sameSopLabel
        if (sopid) {
          const caseItem = res.data.items.find((item: any) => item.id === Number(sopid))
          if (caseItem) {
            setSameSopLabel({ ...caseItem }) // Uncomment if you have this state
            setIsLingsi(true)
          }
        } else if (sopName && sopSharePath) {
          setSameSopLabel({ id: '', name: decodeURIComponent(sopName), url: decodeURIComponent(sopSharePath) })
          setIsLingsi(true)
        }
      } catch (error) {
        console.error("Error loading initial cases:", error)
      }
    }

    loadInitialData()
  }, [sopid, setIsLingsi])

  if (!isLingsi) return null
  if (casesData.length === 0) return null

  return (
    <div className="relative w-full mt-8 pb-20">
      <p className="text-sm text-center text-gray-400">{t("com_case_featured")}</p>
      <div className="flex flex-wrap pt-4 mx-auto gap-2 w-[782px]">
        {casesData.map((caseItem) => (
          <Card
            key={caseItem.id}
            className="w-[254px] py-0 rounded-2xl shadow-none hover:shadow-xl group relative overflow-hidden"
          >
            <CardContent className="flex flex-col justify-between h-[98px] p-4">
              {/* 信息位：标题 */}
              <div className="text-sm font-medium text-gray-800 line-clamp-2">{caseItem.name}</div>

              {/* 动作位：按钮组（右下角，hover 时显示） */}
              <div className="absolute bottom-2 right-4 flex justify-end space-x-2 mt-2 opacity-0 translate-y-2 group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-300">
                <Button
                  variant="default"
                  className="bg-primary text-white rounded-full h-8 px-3 text-xs flex items-center space-x-0"
                  onClick={() => setSameSopLabel({ ...caseItem })}
                >
                  <MousePointerClick className="w-3.5 h-3.5" />
                  <span>{t("com_make_samestyle")}</span>
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
  )
})