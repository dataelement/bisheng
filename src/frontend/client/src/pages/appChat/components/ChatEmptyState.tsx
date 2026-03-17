interface ChatEmptyStateProps {
  onNewChat: () => void;
}

/**
 * Empty state for chat area when there are no conversations.
 * Centered illustration with prompt text and a clickable link to start a new chat.
 * Matches Figma design node 2916:10272.
 */
export function ChatEmptyState({ onNewChat }: ChatEmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4">
      {/* Illustration image */}
      <img 
        src={`${__APP_ENV__.BASE_URL || ''}/assets/channel/ai-home.png`} 
        alt="Empty chat" 
        className="w-[80px] h-[80px] mb-[22px] object-contain"
      />
      {/* Prompt text */}
      <p className="text-[14px] text-[#86909c] leading-[22px]">
        还没有任何历史对话，
        <button
          onClick={onNewChat}
          className="text-primary hover:underline font-medium cursor-pointer bg-transparent border-none p-0 inline"
        >
          开始一个新的对话吧
        </button>
      </p>
    </div>
  );
}
