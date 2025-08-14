import { ArrowRight } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import type { ChatFormValues } from '~/common';
import { Spinner } from '~/components/svg';
import type { TMessage } from '~/data-provider/data-provider/src';
import { useGetMessagesByConvoId } from '~/data-provider/data-provider/src/react-query';
import { useAddedResponse, useChatHelpers, useSSE } from '~/hooks';
import { AddedChatContext, ChatContext, ChatFormProvider, useFileMapContext } from '~/Providers';
import store from '~/store';
import { buildTree, cn } from '~/utils';
import { Button } from '../ui';
import HeaderTitle from './HeaderTitle';
import ChatForm from './Input/ChatForm';
import InvitationCodeForm from './InviteCode';
import Landing from './Landing';
import MessagesView from './Messages/MessagesView';
import Presentation from './Presentation';

function ChatView({ index = 0 }: { index?: number }) {
  const { conversationId } = useParams();
  const rootSubmission = useRecoilValue(store.submissionByIndex(index));
  const addedSubmission = useRecoilValue(store.submissionByIndex(index + 1));
  const [showCode, setShowCode] = useState(false);

  const navigate = useNavigate();
  const fileMap = useFileMapContext();
  // console.log('fileMap :>> ', fileMap);

  // his messages
  const { data: messagesTree = null, isLoading } = useGetMessagesByConvoId(conversationId ?? '', {
    select: useCallback(
      (data: TMessage[]) => {
        // 转树结构
        const dataTree = buildTree({ messages: data, fileMap });
        return dataTree?.length === 0 ? null : (dataTree ?? null);
      },
      [fileMap],
    ),
    enabled: !!fileMap,
  });

  console.log('messagesTree :>> ', rootSubmission, messagesTree);

  const [isLingsi, setIsLingsi] = useState(false);
  const chatHelpers = useChatHelpers(index, conversationId, isLingsi);
  const addedChatHelpers = useAddedResponse({ rootIndex: index });

  useSSE(rootSubmission, chatHelpers, false); // rootSubmission变化触发SSE
  useSSE(addedSubmission, addedChatHelpers, true);

  const methods = useForm<ChatFormValues>({
    defaultValues: { text: '' },
  });

  // 会话关闭linsight模式
  useEffect(() => {
    if (messagesTree && messagesTree.length !== 0) {
      setIsLingsi(false);
    }
  }, [messagesTree])

  const isNew = conversationId === 'new';
  let content: JSX.Element | null | undefined;
  if (isLoading && conversationId !== 'new') {
    content = (
      <div className="flex h-screen items-center justify-center">
        <Spinner className="opacity-0" />
      </div>
    );
  } else if (messagesTree && messagesTree.length !== 0) {
    content = <MessagesView messagesTree={messagesTree} Header={
      // 会话标题
      <HeaderTitle conversation={chatHelpers?.conversation} />
    } />;
  } else {
    // content = <Landing Header={<Header />} />;
    // 欢迎页
    content = <Landing lingsi={isLingsi} setLingsi={setIsLingsi} isNew={isNew} />;
  }

  const selfHost = location.host.indexOf('bisheng') !== -1;

  return (
    <ChatFormProvider {...methods}>
      <ChatContext.Provider value={chatHelpers}>
        <AddedChatContext.Provider value={addedChatHelpers}>
          <Presentation>
            <div className={cn(`relative flex h-full flex-col overflow-hidden`, isNew && 'justify-center',)}>
              {/* 背景图片层 */}
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
              // src={`${__APP_ENV__.BASE_URL}/assets/linsi-bg.mp4`}
              >
                <source
                  src={`${__APP_ENV__.BASE_URL}/assets/linsi-bg.mp4`}
                  type="video/mp4"
                />
                <img
                  src={`${__APP_ENV__.BASE_URL}/assets/lingsi-bg.png`}
                  alt=""
                />
              </video>
              {/* his messages */}
              <div className={showCode ? "hidden" : "flex h-full flex-col justify-center"}>
                {content}
                <div className="w-full border-t-0 pl-0 pt-2 dark:border-white/20 md:w-[calc(100%-.5rem)] md:border-t-0 md:border-transparent md:pl-0 md:pt-0 md:dark:border-transparent">
                  {/* input */}
                  <ChatForm isLingsi={isLingsi} setShowCode={setShowCode} index={index} />
                  <div className="h-[2vh]"></div>
                </div>
              </div>
              {/* <Footer /> */}
              {isLingsi && selfHost && <Cases />}
              {/*   邀请码 */}
              <InvitationCodeForm showCode={showCode} setShowCode={setShowCode} />
            </div>
          </Presentation>
        </AddedChatContext.Provider>
      </ChatContext.Provider>
    </ChatFormProvider >
  );
}

export default memo(ChatView);


const Cases = () => {

  const casesData = [
    { id: 'case1', title: '超详细日本7日旅游攻略' },
    { id: 'case2', title: '招股书说明书和君七步法阅读报告' },
    { id: 'case3', title: '招标需求响应' },
    { id: 'case4', title: '近6个月AI新产品盘点（广度搜索）' },
    { id: 'case5', title: '制作一个航空航天科普网站' },
    { id: 'case6', title: '魔塔网页小游戏' }
  ];

  const handleCardClick = (caseId: string) => {
    window.open(`${__APP_ENV__.BASE_URL}/linsight/${caseId}`)
  }

  return (
    <div className='absolute bottom-8 w-full mt-20'>
      <p className='text-sm text-center text-gray-400'>灵思精选案例</p>
      <div className='flex pt-4 justify-center mx-auto gap-2 px-12'>
        {casesData.map((caseItem) => (
          <div
            key={caseItem.id}
            className='w-72 relative border border-gray-100 rounded-xl py-4 p-5 text-sm hover:shadow-xl cursor-pointer bg-white/40'
            onClick={() => handleCardClick(caseItem.id)}
          >
            <Button
              className='absolute bottom-3 right-3 p-0 h-6 w-6 shadow-md border-none'
              variant="outline"
              size="icon"
            >
              <ArrowRight size="14" />
            </Button>
            <p>{caseItem.title}</p>
          </div>
        ))}
      </div>
    </div>
  );
};