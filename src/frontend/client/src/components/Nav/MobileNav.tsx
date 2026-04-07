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
    <div className="bg-token-main-surface-primary sticky top-0 z-10 flex min-h-[48px] w-full flex-row items-center justify-between bg-white max-[575px]:bg-[#f9f9fb] px-1 pl-2 pr-3 dark:bg-gray-800 dark:text-white md:hidden max-[575px]:border-b max-[575px]:border-[#f0f1f3]">
      <button
        type="button"
        data-testid="mobile-header-toggle-sidebar"
        aria-label={navVisible ? localize('com_nav_close_sidebar') : localize('com_nav_open_sidebar')}
        aria-expanded={navVisible}
        className="inline-flex size-10 shrink-0 items-center justify-center rounded-full text-[#1d2129] hover:bg-surface-hover"
        onClick={toggleSidebar}
      >
        {navVisible ? (
          <X className="size-6" strokeWidth={2} />
        ) : (
          <Menu className="size-6" strokeWidth={2} />
        )}
      </button>
      {variant === 'app' ? (
        <h1 className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-center text-sm font-normal max-[575px]:sr-only">
          {title ?? localize('com_ui_new_chat')}
        </h1>
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
        className="inline-flex size-10 shrink-0 items-center justify-center rounded-full text-[#1d2129] hover:bg-surface-hover"
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
        <Plus className="size-6" strokeWidth={2} />
      </button>
    </div>
  );
}
