import React from 'react';
import { useRecoilValue } from 'recoil';
import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, Menu, Plus, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { QueryKeys, Constants } from '~/types/chat';
import type { TMessage } from '~/types/chat';
import type { Dispatch, SetStateAction } from 'react';
import ShareChat from '~/components/Share/ShareChat';
import { useLocalize, useNewConvo } from '~/hooks';
import { cn } from '~/utils';
import store from '~/store';

const shareChatTypes = {
  1: 'skill',
  5: 'assistant',
  10: 'workflow',
  15: 'workbench_chat',
} as const;

type MobileNavProps = {
  variant?: 'chat' | 'app';
  navVisible: boolean;
  setNavVisible: Dispatch<SetStateAction<boolean>>;
  persistNavVisibleInLocalStorage?: boolean;
  navigateToNewChatPath?: string | false;
  onNewChat?: () => void;
  preferBackButton?: boolean;
  onBack?: () => void;
};

/**
 * 移动端顶栏：左会话抽屉、右新建。
 * 主站 chat：中间不展示标题（收起态无左侧窄栏）。
 */
export default function MobileNav({
  variant = 'chat',
  navVisible,
  setNavVisible,
  persistNavVisibleInLocalStorage = true,
  navigateToNewChatPath = '/c/new',
  onNewChat,
  preferBackButton = false,
  onBack,
}: MobileNavProps) {
  const mobileHeadIconBtnClassName =
    'inline-flex size-8 shrink-0 items-center justify-center rounded-md text-[#212121] hover:bg-[#F7F8FA]';
  const localize = useLocalize();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { newConversation } = useNewConvo();
  const conversation = useRecoilValue(store.conversationByIndex(0));
  const { title = 'New Chat' } = conversation || {};
  const chatMobileHeader = useRecoilValue(store.chatMobileHeaderState);
  const showWorkbenchMergedBar =
    variant === 'chat' && chatMobileHeader !== null;

  const toggleSidebar = () => {
    setNavVisible((prev) => {
      const next = !prev;
      if (persistNavVisibleInLocalStorage) {
        localStorage.setItem('navVisible', JSON.stringify(next));
      }
      return next;
    });
  };

  const handleNewChat = () => {
    if (onNewChat) {
      onNewChat();
      return;
    }
    queryClient.setQueryData<TMessage[]>(
      [QueryKeys.messages, conversation?.conversationId ?? Constants.NEW_CONVO],
      [],
    );
    newConversation();
    if (navigateToNewChatPath !== false) {
      navigate(navigateToNewChatPath);
    }
  };

  const shareType =
    showWorkbenchMergedBar && chatMobileHeader
      ? shareChatTypes[chatMobileHeader.flowType as keyof typeof shareChatTypes]
      : undefined;

  return (
    <div
      className={cn(
        'bg-token-main-surface-primary sticky top-0 z-10 w-full bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)] dark:bg-gray-800 dark:text-white',
      )}
    >
      <div
        className={cn(
          'flex h-11 min-h-11 w-full flex-row items-center justify-between px-4',
        )}
      >
        <button
          type="button"
          data-testid="mobile-header-left-action"
          aria-label={preferBackButton ? localize('com_ui_go_back') : (navVisible ? localize('com_nav_close_sidebar') : localize('com_nav_open_sidebar'))}
          aria-expanded={preferBackButton ? undefined : navVisible}
          className={mobileHeadIconBtnClassName}
          onClick={preferBackButton ? (onBack ?? toggleSidebar) : toggleSidebar}
        >
          {preferBackButton ? (
            <ChevronLeft className="size-4" strokeWidth={2} />
          ) : navVisible ? (
            <X className="size-4" strokeWidth={2} />
          ) : (
            <Menu className="size-4" strokeWidth={2} />
          )}
        </button>
        {showWorkbenchMergedBar && chatMobileHeader ? (
          <>
            <div className="min-w-0 flex-1 px-1 flex justify-center">
              <span
                id="app-title"
                className="truncate text-center text-[14px] font-medium leading-[22px] text-[#212121]"
                title={chatMobileHeader.title}
              >
                {chatMobileHeader.title}
              </span>
            </div>
            <div className="flex shrink-0 items-center gap-0.5">
              {!chatMobileHeader.readOnly && !chatMobileHeader.hideShare && shareType && (
                <ShareChat
                  type={shareType}
                  flowId={chatMobileHeader.flowId || undefined}
                  chatId={chatMobileHeader.conversationId}
                />
              )}
              <button
                type="button"
                data-testid="mobile-header-new-chat-button"
                aria-label={localize('com_ui_new_chat')}
                className={mobileHeadIconBtnClassName}
                onClick={handleNewChat}
              >
                <Plus className="size-4" strokeWidth={2} />
              </button>
            </div>
          </>
        ) : (
          <>
            {variant === 'app' ? (
              <>
                <div className="min-w-0 flex-1" aria-hidden />
                <span className="sr-only">{localize('com_ui_new_chat')}</span>
              </>
            ) : (
              <>
                <div className="min-w-0 flex-1" aria-hidden />
                <span className="sr-only">{title ?? localize('com_ui_new_chat')}</span>
              </>
            )}
            <button
              type="button"
              data-testid="mobile-header-new-chat-button"
              aria-label={localize('com_ui_new_chat')}
              className={mobileHeadIconBtnClassName}
              onClick={handleNewChat}
            >
              <Plus className="size-4" strokeWidth={2} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
