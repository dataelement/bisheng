import { useMemo, memo } from 'react';
import { parseISO, isToday } from 'date-fns';
import { TConversation } from '~/types/chat';
import { useLocalize } from '~/hooks';
import Convo from './Convo';

interface ConversationsProps {
  conversations: Array<TConversation | null>;
  moveToTop: () => void;
  toggleNav: () => void;
}

const Conversations = ({ conversations, moveToTop, toggleNav }: ConversationsProps) => {
  const localize = useLocalize();
  const recent = useMemo(() => conversations.filter((convo): convo is TConversation => !!convo)
    .sort((a, b) => (Date.parse(b.updatedAt || '') || 0) - (Date.parse(a.updatedAt || '') || 0)), [conversations]);
  const firstTodayConvoId = recent.find(convo => convo.updatedAt && isToday(parseISO(convo.updatedAt)))?.conversationId;

  return (
    <section aria-label={localize('chat.sidebar.recent')} className="dsh-history-list">
      <div className="dsh-history-group text-caption text-text-3">{localize('chat.sidebar.recent')}</div>
      {recent.map(convo => (
        <Convo
          key={convo.conversationId}
          isLatestConvo={convo.conversationId === firstTodayConvoId}
          conversation={convo}
          retainView={moveToTop}
          toggleNav={toggleNav}
        />
      ))}
    </section>
  );
};

export default memo(Conversations);
