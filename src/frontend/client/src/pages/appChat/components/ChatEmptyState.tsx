import { useLocalize } from '~/hooks';
import { ArticleQAIllustration } from '~/components/illustrations';

interface ChatEmptyStateProps {
  onNewChat: () => void;
}

/**
 * 应用对话主区空状态：居中插画 + 提示文案，「开始新对话」可点击跳转新会话。
 */
export function ChatEmptyState({ onNewChat }: ChatEmptyStateProps) {
  const localize = useLocalize();
  return (
    <div className="flex h-full min-h-0 w-full flex-col items-center justify-center px-4 text-center">
      <ArticleQAIllustration grey className="mb-4 h-20 w-20" />
      <p className="max-w-[280px] text-[14px] font-normal leading-[22px] text-[#999999]">
        {localize('com_app_chat_empty_line1')}
        <button
          type="button"
          onClick={onNewChat}
          className="inline border-none bg-transparent p-0 font-medium text-primary hover:underline"
        >
          {localize('com_app_chat_empty_cta')}
        </button>
      </p>
    </div>
  );
}
