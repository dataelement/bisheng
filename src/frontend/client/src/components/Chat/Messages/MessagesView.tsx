import { useState } from 'react';
import { MessageSquare, MessagesSquareIcon, Search } from 'lucide-react';
import { useRecoilValue } from 'recoil';
import { useNavigate } from 'react-router-dom';
import { CSSTransition } from 'react-transition-group';
import type { ReactNode } from 'react';
import type { TMessage } from '~/data-provider/data-provider/src';
import { useScreenshot, useMessageScrolling, useLocalize, useNewConvo } from '~/hooks';
import ScrollToBottom from '~/components/Messages/ScrollToBottom';
import MultiMessage from './MultiMessage';
import { cn } from '~/utils';
import store from '~/store';

export default function MessagesView({
  messagesTree: _messagesTree,
  Header,
}: {
  messagesTree?: TMessage[] | null;
  Header?: ReactNode;
}) {
  const { newConversation: newConvo } = useNewConvo(0);
  const navigate = useNavigate();
  const localize = useLocalize();
  const scrollButtonPreference = useRecoilValue(store.showScrollButton);
  const fontSize = useRecoilValue(store.fontSize);
  const { screenshotTargetRef } = useScreenshot();
  const [currentEditId, setCurrentEditId] = useState<number | string | null>(-1);

  const {
    conversation,
    scrollableRef,
    messagesEndRef,
    showScrollButton,
    handleSmoothToRef,
    debouncedHandleScroll,
  } = useMessageScrolling(_messagesTree);

  const { conversationId } = conversation ?? {};

  return (
    // 消息面板
    <div className="flex-1 overflow-hidden overflow-y-auto">
      <div className="relative h-full">
        <div
          className="scrollbar-gutter-stable flex flex-grow flex-col"
          onScroll={debouncedHandleScroll}
          ref={scrollableRef}
          style={{
            height: '100%',
            overflowY: 'auto',
            width: '100%',
          }}
        >
          <div className="flex flex-1 flex-col pb-3 dark:bg-transparent">
            {(_messagesTree && _messagesTree.length == 0) || _messagesTree === null ? (
              <div
                className={cn(
                  'flex w-full items-center justify-center p-3 text-text-secondary',
                  fontSize,
                )}
              >
                {localize('com_ui_nothing_found')}
              </div>
            ) : (
              <>
                {Header != null && Header}
                <div ref={screenshotTargetRef}>
                  <MultiMessage
                    key={conversationId} // avoid internal state mixture
                    messagesTree={_messagesTree}
                    messageId={conversationId ?? null}
                    setCurrentEditId={setCurrentEditId}
                    currentEditId={currentEditId ?? null}
                  />
                </div>
              </>
            )}
            <div
              id="messages-end"
              className="group h-0 w-full flex-shrink-0"
              ref={messagesEndRef}
            />
          </div>
        </div>
        {/* 开启新对话 */}
        <div className='absolute bottom-12 h-0 w-full flex justify-center'>
          <button
            className="flex items-center h-8 justify-center gap-2 rounded-2xl bg-blue-100 px-4 py-1 font-medium text-blue-main hover:bg-blue-200"
            onClick={() => {
              newConvo();
              navigate('/c/new');
            }}
            aria-label={localize('com_ui_new_chat')}
          >
            <img className='size-5' src={__APP_ENV__.BASE_URL + '/assets/chat.png'} alt="" />
            <span className="text-sm">{localize('com_ui_new_chat')}</span>
          </button>
        </div>
        {/* 返回底部 */}
        <CSSTransition
          in={showScrollButton}
          timeout={400}
          classNames="scroll-down"
          unmountOnExit={false}
        // appear
        >
          {() =>
            showScrollButton &&
            scrollButtonPreference && <ScrollToBottom scrollHandler={handleSmoothToRef} />
          }
        </CSSTransition>
      </div>
    </div>
  );
}
