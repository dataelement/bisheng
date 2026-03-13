import { useMemo, memo } from 'react';
import { parseISO, isToday } from 'date-fns';
import { TConversation } from '~/data-provider/data-provider/src';
import { useLocalize, TranslationKeys } from '~/hooks';
import { groupConversationsByDate } from '~/utils';
import Convo from './Convo';

const Conversations = ({
  conversations,
  moveToTop,
  toggleNav,
}: {
  conversations: Array<TConversation | null>;
  moveToTop: () => void;
  toggleNav: () => void;
}) => {
  const localize = useLocalize();
  const groupedConversations = useMemo(
    () => groupConversationsByDate(conversations),
    [conversations],
  );
  const firstTodayConvoId = useMemo(
    () =>
      conversations.find((convo) => convo && convo.updatedAt && isToday(parseISO(convo.updatedAt)))
        ?.conversationId,
    [conversations],
  );

  return (
    <div className="text-token-text-primary flex flex-col gap-2 pb-2 text-sm">
      <div>
        {groupedConversations.map(([groupName, convos]) => (
          <div key={groupName}>
            <div
              className="text-black opacity-60 px-[12px] pt-4 text-[12px] mb-1"
            >
              {/* time */}
              {localize(groupName as TranslationKeys) || groupName}
            </div>
            {convos.map((convo, i) => (
              <Convo
                key={`${groupName}-${convo.conversationId}-${i}`}
                isLatestConvo={convo.conversationId === firstTodayConvoId}
                conversation={convo}
                retainView={moveToTop}
                toggleNav={toggleNav}
              />
            ))}
            <div
              style={{
                marginTop: '5px',
                marginBottom: '5px',
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default memo(Conversations);
