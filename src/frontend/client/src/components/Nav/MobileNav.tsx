import React, { useState } from 'react';
import { useRecoilValue, useSetRecoilState } from 'recoil';
import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, Menu, X } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import { useNavigate } from 'react-router-dom';
import { QueryKeys, Constants } from '~/types/chat';
import type { TMessage } from '~/types/chat';
import type { Dispatch, SetStateAction } from 'react';
import ShareChat from '~/components/Share/ShareChat';
import { useLocalize, useNewConvo } from '~/hooks';
import { cn } from '~/utils';
import store from '~/store';
import { MobileChatHistoryDropdown } from './MobileChatHistoryDropdown';

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
  /** 应用内对话：无合并标题时与侧栏并排展示「返回」；有会话标题时返回在侧栏内，顶栏仅抽屉 */
  appSurfaceBackAction?: () => void;
  /** App-surface: opens the app-chat history dropdown (app card + conversation list).
   *  Caret/grey states key off `appHistoryDropdownOpen`; the dropdown itself is rendered
   *  by AppRoot since it needs the /app/* route context for `useAppSidebar`. */
  appHistoryDropdownOpen?: boolean;
  onToggleAppHistoryDropdown?: () => void;
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
  appSurfaceBackAction,
  appHistoryDropdownOpen = false,
  onToggleAppHistoryDropdown,
}: MobileNavProps) {
  const mobileHeadIconBtnClassName =
    'inline-flex size-5 shrink-0 items-center justify-center text-[#212121]';
  const localize = useLocalize();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { newConversation } = useNewConvo();
  const conversation = useRecoilValue(store.conversationByIndex(0));
  const { title = 'New Chat' } = conversation || {};
  const chatMobileHeader = useRecoilValue(store.chatMobileHeaderState);
  const setSystemMenuOpen = useSetRecoilState(store.mobileSystemMenuOpenState);
  /** H5: 标题下拉(对话列表)展开状态 */
  const [historyDropdownOpen, setHistoryDropdownOpen] = useState(false);
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

  /** 应用内对话：有合并标题时顶栏与主站对话一致（左仅抽屉、中标题、右分享+新建）；无标题时保留「菜单+返回」 */
  const appSurfaceShowBackWithMenu =
    Boolean(
      appSurfaceBackAction &&
        !preferBackButton &&
        !(showWorkbenchMergedBar && chatMobileHeader),
    );

  const appBackBtnClassName =
    'inline-flex size-8 shrink-0 items-center justify-center rounded-lg border border-[#E5E6EB] bg-white text-[#212121] shadow-sm transition-colors hover:bg-[#F7F8FA]';

  return (
    <div
      className={cn(
        'bg-token-main-surface-primary sticky top-0 z-10 w-full bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)] dark:bg-gray-800 dark:text-white',
      )}
    >
      <div
        className={cn(
          'relative flex h-11 min-h-11 w-full flex-row items-center justify-between px-4',
        )}
      >
        {appSurfaceShowBackWithMenu ? (
          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              data-testid="mobile-header-left-action"
              aria-label={navVisible ? localize('com_nav_close_sidebar') : localize('com_nav_open_sidebar')}
              aria-expanded={navVisible}
              className={appBackBtnClassName}
              onClick={toggleSidebar}
            >
              {navVisible ? (
                <X className="size-4" strokeWidth={2} />
              ) : (
                <Menu className="size-4" strokeWidth={2} />
              )}
            </button>
            <button
              type="button"
              data-testid="mobile-header-app-back"
              aria-label={localize('com_ui_go_back')}
              className={appBackBtnClassName}
              onClick={appSurfaceBackAction}
            >
              <ChevronLeft className="size-4" strokeWidth={2} />
            </button>
          </div>
        ) : (
          <button
            type="button"
            data-testid="mobile-header-left-action"
            aria-label={preferBackButton ? localize('com_ui_go_back') : localize('com_nav_open_sidebar')}
            className={cn(
              mobileHeadIconBtnClassName,
              (historyDropdownOpen || appHistoryDropdownOpen) && 'pointer-events-none text-[#C9CDD4]',
            )}
            onClick={preferBackButton ? (onBack ?? toggleSidebar) : () => { setHistoryDropdownOpen(false); setSystemMenuOpen(true); }}
          >
            {preferBackButton ? (
              <ChevronLeft className="size-4" strokeWidth={2} />
            ) : (
              <Outlined.SidebarMenu className="size-5" />
            )}
          </button>
        )}
        {showWorkbenchMergedBar && chatMobileHeader ? (
          <>
            {/* Title is absolutely screen-centered (left-1/2 + -translate-x-1/2)
                instead of flex-centered between the side buttons, so it stays at
                the true horizontal midpoint regardless of how many icons sit on
                either edge. max-w reserves room for the menu (left) and the
                share + new-chat icons (right) so a long title truncates rather
                than sliding under them. Mirrors the 知识空间 / 订阅 mobile headers. */}
            <div className="absolute left-1/2 top-0 flex h-full max-w-[calc(100%-128px)] -translate-x-1/2 items-center justify-center px-1">
              {appSurfaceBackAction ? (
                // App-surface chat: title opens the app-chat history dropdown (app card
                // + conversation list). The dropdown itself is rendered by AppRoot which
                // owns the /app/* route context required by `useAppSidebar`.
                onToggleAppHistoryDropdown ? (
                  <button
                    type="button"
                    id="app-title"
                    onClick={onToggleAppHistoryDropdown}
                    aria-expanded={appHistoryDropdownOpen}
                    title={chatMobileHeader.title}
                    className="flex min-w-0 max-w-full items-center justify-center gap-1 outline-none"
                  >
                    <span className="truncate text-[14px] font-medium leading-[22px] text-[#212121]">
                      {chatMobileHeader.title}
                    </span>
                    <Outlined.Down
                      className={cn(
                        'size-4 shrink-0 text-[#86909C] transition-transform',
                        appHistoryDropdownOpen && 'rotate-180',
                      )}
                    />
                  </button>
                ) : (
                  <span
                    id="app-title"
                    className="truncate text-center text-[14px] font-medium leading-[22px] text-[#212121]"
                    title={chatMobileHeader.title}
                  >
                    {chatMobileHeader.title}
                  </span>
                )
              ) : (
                // Main /c/* chat: title stays clickable after a conversation loads so the
                // user can re-open the history dropdown and switch to another conversation.
                <button
                  type="button"
                  id="app-title"
                  onClick={() => setHistoryDropdownOpen((o) => !o)}
                  aria-expanded={historyDropdownOpen}
                  title={chatMobileHeader.title}
                  className="flex min-w-0 max-w-full items-center justify-center gap-1 outline-none"
                >
                  <span className="truncate text-[14px] font-medium leading-[22px] text-[#212121]">
                    {chatMobileHeader.title}
                  </span>
                  <Outlined.Down
                    className={cn(
                      'size-4 shrink-0 text-[#86909C] transition-transform',
                      historyDropdownOpen && 'rotate-180',
                    )}
                  />
                </button>
              )}
            </div>
            <div
              className={cn(
                // 12px gap between the share and new-chat icon buttons.
                'flex shrink-0 items-center gap-3',
                // Match the non-merged branch: while either history dropdown is open, dim
                // and disable adjacent icons so the only available action is selecting/
                // closing the list. Main-chat dropdown only applies outside app surface;
                // app-history dropdown only applies inside app surface.
                ((historyDropdownOpen && !appSurfaceBackAction) ||
                  (appHistoryDropdownOpen && appSurfaceBackAction)) &&
                  'pointer-events-none text-[#C9CDD4]',
              )}
            >
              {!chatMobileHeader.readOnly && !chatMobileHeader.hideShare && shareType && (
                <ShareChat
                  type={shareType}
                  flowId={chatMobileHeader.flowId || undefined}
                  chatId={chatMobileHeader.conversationId}
                  iconClassName="size-5 shrink-0"
                  buttonClassName={cn(mobileHeadIconBtnClassName, 'p-0 hover:bg-transparent')}
                />
              )}
              <button
                type="button"
                data-testid="mobile-header-new-chat-button"
                aria-label={localize('com_ui_new_chat')}
                className={mobileHeadIconBtnClassName}
                onClick={handleNewChat}
              >
                <Outlined.Plus className="size-5" />
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
              // Wrapper centers within the bar; the button itself is content-width so only
              // the title + caret is tappable (avoids mis-tapping the ≡ / + on the edges).
              <div className="flex min-w-0 flex-1 justify-center px-1">
                <button
                  type="button"
                  onClick={() => setHistoryDropdownOpen((o) => !o)}
                  aria-expanded={historyDropdownOpen}
                  className="flex min-w-0 max-w-full items-center justify-center gap-1 outline-none"
                >
                  <span className="truncate text-[14px] font-medium leading-[22px] text-[#212121]">
                    {localize('com_ui_chat_list')}
                  </span>
                  <Outlined.Down
                    className={cn(
                      'size-4 shrink-0 text-[#86909C] transition-transform',
                      historyDropdownOpen && 'rotate-180',
                    )}
                  />
                </button>
              </div>
            )}
            <button
              type="button"
              data-testid="mobile-header-new-chat-button"
              aria-label={localize('com_ui_new_chat')}
              className={cn(
                mobileHeadIconBtnClassName,
                (historyDropdownOpen || appHistoryDropdownOpen) && 'pointer-events-none text-[#C9CDD4]',
              )}
              onClick={handleNewChat}
            >
              <Outlined.Plus className="size-5" />
            </button>
          </>
        )}
      </div>
      <MobileChatHistoryDropdown
        open={historyDropdownOpen}
        onClose={() => setHistoryDropdownOpen(false)}
        onNewChat={handleNewChat}
      />
    </div>
  );
}
