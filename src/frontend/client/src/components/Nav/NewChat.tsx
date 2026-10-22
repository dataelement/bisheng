import { useQueryClient } from '@tanstack/react-query';
import { Outlined } from 'bisheng-icons';
import { useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSetRecoilState } from 'recoil';
import { taskModeState } from '~/store/linsight';
import type { TMessage } from '~/types/chat';
import { Constants, QueryKeys } from '~/types/chat';
import { useLocalize, useNewConvo } from '~/hooks';
import store from '~/store';
import { Button } from '../ui';

/** Same delay the 新建对话 button below uses for its second reset pass. */
const SECOND_PASS_DELAY_MS = 300;

/**
 * 新建对话 for entries that live outside the chat route (the workbench sidebar).
 * Mirrors the button below: reset the conversation, leave task mode, land on /c/new
 * and clear the cached message list — then repeat once, because the first pass alone
 * does not fully reset an open conversation. Lives here (not next to its caller)
 * because it needs recoil, which is frozen for new files.
 */
export function useStartNewChat(): () => void {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { newConversation } = useNewConvo(0);
  const { conversation } = store.useCreateConversationAtom(0);
  const setTaskMode = useSetRecoilState(taskModeState);
  const timerRef = useRef<number | null>(null);

  // Latest values for the delayed second pass, which must not run a stale closure.
  const resetRef = useRef<() => void>(() => undefined);
  resetRef.current = () => {
    newConversation();
    setTaskMode(false);
    navigate('/c/new');
    queryClient.setQueryData<TMessage[]>(
      [QueryKeys.messages, conversation?.conversationId ?? Constants.NEW_CONVO],
      [],
    );
  };

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  return useCallback(() => {
    resetRef.current();
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      resetRef.current();
    }, SECOND_PASS_DELAY_MS);
  }, []);
}

export default function NewChat({
  index = 0,
  toggleNav,
  subHeaders,
  isSmallScreen,
  showToggleButton = true,
}: {
  index?: number;
  toggleNav: () => void;
  subHeaders?: React.ReactNode;
  isSmallScreen: boolean;
  showToggleButton?: boolean;
}) {
  const queryClient = useQueryClient();
  /** Note: this component needs an explicit index passed if using more than one */
  const { newConversation: newConvo } = useNewConvo(index);
  const navigate = useNavigate();
  const setTaskMode = useSetRecoilState(taskModeState);
  const localize = useLocalize();

  const { conversation } = store.useCreateConversationAtom(index);

  const handleNewChat = () => {
      newConvo();
      // Reset the global atom directly (KeepAlive-cached ChatView won't re-run
      // its location effect after a tab switch — see taskModeState).
      setTaskMode(false);
      navigate('/c/new');
      // Keep auto-collapse behavior only on small screens.
      if (isSmallScreen) {
        toggleNav();
      }
      queryClient.setQueryData<TMessage[]>(
        [QueryKeys.messages, conversation?.conversationId ?? Constants.NEW_CONVO],
        [],
      );
  };

  return (
    <div className="dsh-history-header">
      <div className="dsh-history-titlebar">
        <span className="text-body-sm font-medium">{localize('chat.sidebar.title')}</span>
        {showToggleButton && (
          <Button
          variant="ghost"
          size="small"
          iconOnly
            title={localize('com_nav_close_sidebar')}
            aria-label={localize('com_nav_close_sidebar')}
            aria-controls="chat-history-nav"
            aria-expanded
            onClick={toggleNav}
            className="dsh-history-toggle"
          >
            <Outlined.SidebarMenu className="size-4" />
          </Button>
        )}
      </div>
      <Button
        variant="outline"
        className="dsh-history-new-chat"
        aria-label={localize('com_ui_new_chat')}
        onClick={handleNewChat}
      >
        <Outlined.MessagePlus size={16} />
        <span>{localize('chat.sidebar.newConversation')}</span>
      </Button>
      {subHeaders}
    </div>
  );
}
