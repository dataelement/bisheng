import { useQueryClient } from '@tanstack/react-query';
import { Outlined } from 'bisheng-icons';
import { useNavigate } from 'react-router-dom';
import { useSetRecoilState } from 'recoil';
import { taskModeState } from '~/store/linsight';
import type { TMessage } from '~/types/chat';
import { Constants, QueryKeys } from '~/types/chat';
import { useLocalize, useNewConvo } from '~/hooks';
import store from '~/store';
import { Button } from '../ui';

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
