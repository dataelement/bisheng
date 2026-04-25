import { Plus, MessageSquare } from 'lucide-react';
import type { AppConversation, ConversationGroup } from '~/@types/app';
import { cn } from '~/utils';

interface ConversationListProps {
  groups: ConversationGroup[];
  activeId?: string;
  onSelect: (conv: AppConversation) => void;
  onNewChat: () => void;
  /** Pass useLocalize(); group.label is an i18n key for date buckets or a year string. */
  localize: (key: string) => string;
}

function formatGroupHeading(label: string, localize: (key: string) => string) {
  return label.startsWith('com_ui_date_') || label.startsWith('com_') ? localize(label) : label;
}

/**
 * Time-grouped conversation list for the app chat sidebar.
 */
export function ConversationList({ groups, activeId, onSelect, onNewChat, localize }: ConversationListProps) {
  if (groups.length === 0) {
    return null; // Parent will show ChatEmptyState
  }

  return (
    <div className="flex-1 overflow-y-auto px-3">
      {groups.map((group) => (
        <div key={group.label} className="mb-2">
          <div className="px-2 mb-1 text-xs font-medium text-gray-400">
            {formatGroupHeading(group.label, localize)}
          </div>
          {group.conversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => onSelect(conv)}
              className={cn(
                'group flex items-center gap-3 px-3 py-3 rounded-xl cursor-pointer transition-all',
                conv.id === activeId
                  ? 'bg-[#eef4ff] text-blue-600'
                  : 'fine-pointer:hover:bg-gray-100 text-gray-700',
              )}
            >
              <MessageSquare
                size={18}
                className={conv.id === activeId ? 'text-blue-500' : 'text-gray-400'}
              />
              <span className="text-[14px] font-medium truncate">{conv.title}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
