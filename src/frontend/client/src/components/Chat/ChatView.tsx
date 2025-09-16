import { ArrowRight, MousePointerClick } from 'lucide-react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import type { ChatFormValues } from '~/common';
import { Spinner } from '~/components/svg';
import type { TMessage } from '~/data-provider/data-provider/src';
import { useGetMessagesByConvoId } from '~/data-provider/data-provider/src/react-query';
import { useAddedResponse, useChatHelpers, useSSE } from '~/hooks';
import { AddedChatContext, ChatContext, ChatFormProvider, useFileMapContext } from '~/Providers';
import store from '~/store';
import { buildTree, cn } from '~/utils';
import { Button } from '../ui';
import { Card, CardContent } from '../ui/Card';
import HeaderTitle from './HeaderTitle';
import ChatForm from './Input/ChatForm';
import InvitationCodeForm from './InviteCode';
import Landing from './Landing';
import MessagesView from './Messages/MessagesView';
import Presentation from './Presentation';
import { sameSopLabelState } from './Input/SameSopSpan';


const ChatView = ({ index = 0 }: { index?: number }) => {
  const { conversationId } = useParams();
  const rootSubmission = useRecoilValue(store.submissionByIndex(index));
  const addedSubmission = useRecoilValue(store.submissionByIndex(index + 1));
  const [showCode, setShowCode] = useState(false);
  const [inputFloat, setInputFloat] = useState(false);
  const [inputWidth, setInputWidth] = useState(0); // To hold the calculated width

  const navigate = useNavigate();
  const fileMap = useFileMapContext();

  const { data: messagesTree = null, isLoading } = useGetMessagesByConvoId(conversationId ?? '', {
    select: useCallback(
      (data: TMessage[]) => {
        const dataTree = buildTree({ messages: data, fileMap });
        return dataTree?.length === 0 ? null : (dataTree ?? null);
      },
      [fileMap],
    ),
    enabled: !!fileMap,
  });

  const [isLingsi, setIsLingsi] = useState(false);
  const chatHelpers = useChatHelpers(index, conversationId, isLingsi);
  const addedChatHelpers = useAddedResponse({ rootIndex: index });

  useSSE(rootSubmission, chatHelpers, false);
  useSSE(addedSubmission, addedChatHelpers, true);

  const methods = useForm<ChatFormValues>({
    defaultValues: { text: '' },
  });

  useEffect(() => {
    if (messagesTree && messagesTree.length !== 0) {
      setIsLingsi(false);
    }
  }, [messagesTree]);

  // Handle scroll event to trigger float input
  const chatContainerRef = useRef<HTMLDivElement>(null); // 创建 ref
  useEffect(() => {
    let hideLocal = 0
    const handleScroll = (e) => {
      const scrollTop = e.target.scrollTop
      const floatPanne = document.getElementById('floatPanne');
      if (floatPanne) {
        const rect = floatPanne.getBoundingClientRect();
        if (rect.top <= 20) {
          setInputFloat(true);
          setInputWidth(rect.width); // Set the width when floating
          console.log('e :>> ',);
          if (hideLocal === 0) {
            hideLocal = scrollTop
          }
        }
        if (hideLocal > 0 && scrollTop < hideLocal) {
          setInputFloat(false);
          hideLocal = 0
        }
      }
    };

    const chatContainer = chatContainerRef.current;
    if (chatContainer) {
      chatContainer.addEventListener('scroll', handleScroll); // 绑定滚动事件
    }
    return () => {
      if (chatContainer) {
        chatContainer.removeEventListener('scroll', handleScroll); // 清理时移除滚动事件
      }
    };
  }, []);

  const isNew = conversationId === 'new';
  let content: JSX.Element | null | undefined;

  if (isLoading && conversationId !== 'new') {
    content = (
      <div className="flex h-screen items-center justify-center">
        <Spinner className="opacity-0" />
      </div>
    );
  } else if (messagesTree && messagesTree.length !== 0) {
    content = <MessagesView messagesTree={messagesTree} Header={<HeaderTitle conversation={chatHelpers?.conversation} />} />;
  } else {
    content = <Landing lingsi={isLingsi} setLingsi={setIsLingsi} isNew={isNew} />;
  }

  return (
    <ChatFormProvider {...methods}>
      <ChatContext.Provider value={chatHelpers}>
        <AddedChatContext.Provider value={addedChatHelpers}>
          <Presentation>
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
                <div className={showCode ? "hidden" : "flex flex-col justify-center relative h-[calc(100vh-200px)]"}>
                  {content}
                  <div
                    id="floatPanne"
                    className={cn(
                      'w-full border-t-0 pl-0 pt-2 dark:border-white/20 md:w-[calc(100%-.5rem)] md:border-t-0 md:border-transparent md:pl-0 md:pt-0 md:dark:border-transparent',
                      inputFloat ? 'fixed top-0 z-10 bg-white pb-20 md:pt-5' : ''
                    )}
                    style={{ width: inputFloat ? `${inputWidth}px` : '100%' }} // Dynamically set width
                  >
                    <ChatForm isLingsi={isLingsi} setShowCode={setShowCode} index={index} />
                    {!inputFloat && <div className="h-[2vh]"></div>}
                  </div>
                </div>
                {isLingsi && <Cases />}
              </div>
              <InvitationCodeForm showCode={showCode} setShowCode={setShowCode} />
            </div>
          </Presentation>
        </AddedChatContext.Provider>
      </ChatContext.Provider>
    </ChatFormProvider>
  );
};

export default memo(ChatView);


const Cases = () => {
  const [_, setSameSopLabel] = useRecoilState(sameSopLabelState)

  const casesData = window.SopCase.list;

  const handleCardClick = (caseId: string) => {
    window.open(`${__APP_ENV__.BASE_URL}/linsight/${caseId}`)
  }

  return (
    <div className='absolute -bottom-6 w-full mt-20'>
      <p className='text-sm max-w-[1728px] pl-16 text-primary'>灵思精选案例</p>
      <div className='flex pt-4 justify-center mx-auto gap-2 px-12'>
        {casesData.map((caseItem) => (
          <div
            key={caseItem.id}
            className='group w-72 relative border border-gray-50 rounded-xl py-4 pb-12 p-5 text-sm hover:shadow-xl cursor-pointer bg-white/50 hover:-translate-y-10 transition-transform ease-out'
            onClick={() => handleCardClick(caseItem.id)}
          >
            <Button
              className='absolute bottom-2 right-3 p-0 h-6 w-6 shadow-md border-none hidden group-hover:inline-flex'
              variant="outline"
              size="icon"
            >
              <ArrowRight size="14" />
            </Button>
            <p className='text-gray-600'>{caseItem.title}</p>
          </div>
        ))}
      </div>
    </div>
  );
};