import React from 'react';
import { useRecoilValue } from 'recoil';
import { useQueryClient } from '@tanstack/react-query';
import { Menu, Plus, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { QueryKeys, Constants } from '~/types/chat';
import type { TMessage } from '~/types/chat';
import type { Dispatch, SetStateAction } from 'react';
import { useLocalize, useNewConvo } from '~/hooks';
import store from '~/store';

type MobileNavProps = {
  variant?: 'chat' | 'app';
  navVisible: boolean;
  setNavVisible: Dispatch<SetStateAction<boolean>>;
  persistNavVisibleInLocalStorage?: boolean;
  navigateToNewChatPath?: string | false;
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
}: MobileNavProps) {
  const mobileHeadIconBtnClassName =
    'inline-flex size-8 shrink-0 items-center justify-center rounded-md text-[#212121] hover:bg-[#F7F8FA]';
  const localize = useLocalize();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { newConversation } = useNewConvo();
  const conversation = useRecoilValue(store.conversationByIndex(0));
  const { title = 'New Chat' } = conversation || {};

  const toggleSidebar = () => {
    setNavVisible((prev) => {
      const next = !prev;
      if (persistNavVisibleInLocalStorage) {
        localStorage.setItem('navVisible', JSON.stringify(next));
      }
      return next;
    });
  };

  return (
    <div className="bg-token-main-surface-primary sticky top-0 z-10 flex h-10 w-full flex-row items-center justify-between bg-white px-2 dark:bg-gray-800 dark:text-white touch-mobile:border-b touch-mobile:border-[#f0f1f3]">
      <button
        type="button"
        data-testid="mobile-header-toggle-sidebar"
        aria-label={navVisible ? localize('com_nav_close_sidebar') : localize('com_nav_open_sidebar')}
        aria-expanded={navVisible}
        className={mobileHeadIconBtnClassName}
        onClick={toggleSidebar}
      >
        {navVisible ? (
          <X className="size-4" strokeWidth={2} />
        ) : (
          <Menu className="size-4" strokeWidth={2} />
        )}
      </button>
      {variant === 'app' ? (
        <>
          {/* 应用会话标题由 ChatView/HeaderTitle 展示；此处勿用主站会话列表首条标题，否则会误显「首页」等 */}
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
        onClick={() => {
          queryClient.setQueryData<TMessage[]>(
            [QueryKeys.messages, conversation?.conversationId ?? Constants.NEW_CONVO],
            [],
          );
          newConversation();
          if (navigateToNewChatPath !== false) {
            navigate(navigateToNewChatPath);
          }
        }}
      >
        <Plus className="size-4" strokeWidth={2} />
      </button>
    </div>
  );
}
