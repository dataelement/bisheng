import type { TMessage } from '~/data-provider/data-provider/src';
import { useGetMessagesByConvoId } from '~/data-provider/data-provider/src/react-query';
import { memo, useCallback } from 'react';
import { useForm } from 'react-hook-form';
import { useParams } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import type { ChatFormValues } from '~/common';
import { Spinner } from '~/components/svg';
import { useAddedResponse, useChatHelpers, useSSE } from '~/hooks';
import { AddedChatContext, ChatContext, ChatFormProvider, useFileMapContext } from '~/Providers';
import store from '~/store';
import { buildTree, cn } from '~/utils';
import Footer from './Footer';
import HeaderTitle from './HeaderTitle';
import ChatForm from './Input/ChatForm';
import Landing from './Landing';
import MessagesView from './Messages/MessagesView';
import Presentation from './Presentation';

function ChatView({ index = 0 }: { index?: number }) {
  const { conversationId } = useParams();
  const rootSubmission = useRecoilValue(store.submissionByIndex(index));
  const addedSubmission = useRecoilValue(store.submissionByIndex(index + 1));

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

  const chatHelpers = useChatHelpers(index, conversationId);
  const addedChatHelpers = useAddedResponse({ rootIndex: index });

  useSSE(rootSubmission, chatHelpers, false); // rootSubmission变化触发SSE
  useSSE(addedSubmission, addedChatHelpers, true);

  const methods = useForm<ChatFormValues>({
    defaultValues: { text: '' },
  });

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
    content = <Landing isNew={isNew} />;
  }
  return (
    <ChatFormProvider {...methods}>
      <ChatContext.Provider value={chatHelpers}>
        <AddedChatContext.Provider value={addedChatHelpers}>
          <Presentation>
            <div className={cn(`flex h-full flex-col`, isNew && 'justify-center')}>
              {/* his messages */}
              {content}
              <div className="w-full border-t-0 pl-0 pt-2 dark:border-white/20 md:w-[calc(100%-.5rem)] md:border-t-0 md:border-transparent md:pl-0 md:pt-0 md:dark:border-transparent">
                {/* input */}
                <ChatForm index={index} />
                <div className="h-8"></div>
                {/* <Footer /> */}
              </div>
            </div>
          </Presentation>
        </AddedChatContext.Provider>
      </ChatContext.Provider>
    </ChatFormProvider>
  );
}

export default memo(ChatView);
