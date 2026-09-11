import { StateView } from '@bisheng/ui';
import { useLocalize } from '~/hooks';
import { ArticleQAIllustration } from '~/components/illustrations';

interface ChatEmptyStateProps {
  onNewChat: () => void;
}

/**
 * 应用对话主区空状态：居中插画 + 提示文案，「开始新对话」可点击跳转新会话。
 *
 * Panel tier (80px grey art) because the AI dock area is a short container, and
 * the way out is a text link inside the copy rather than a button — 组件-State
 * 状态页.md §3 / §4.3.
 */
export function ChatEmptyState({ onNewChat }: ChatEmptyStateProps) {
  const localize = useLocalize();
  return (
    <StateView
      size="panel"
      image={<ArticleQAIllustration grey />}
      title={
        <>
          {localize('com_app_chat_empty_line1')}
          <button
            type="button"
            onClick={onNewChat}
            className="inline border-none bg-transparent p-0 font-medium text-primary hover:underline"
          >
            {localize('com_app_chat_empty_cta')}
          </button>
        </>
      }
    />
  );
}
