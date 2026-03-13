import { MessageSquare } from 'lucide-react';

interface ChatEmptyStateProps {
  onNewChat: () => void;
}

/**
 * Empty state for chat area when there are no conversations.
 * Shows prompt and a clickable link to start a new chat.
 */
export function ChatEmptyState({ onNewChat }: ChatEmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4">
      <div className="mb-4 opacity-60">
        <MessageSquare size={48} className="text-gray-300" />
      </div>
      <p className="text-sm text-gray-400 mb-2">还没有任何历史对话</p>
      <button
        onClick={onNewChat}
        className="text-sm text-blue-500 hover:text-blue-600 transition-colors font-medium"
      >
        开始一个新的对话吧
      </button>
    </div>
  );
}
