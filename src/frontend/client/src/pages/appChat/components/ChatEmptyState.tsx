import { useLocalize } from '~/hooks';

interface ChatEmptyStateProps {
  onNewChat: () => void;
}

const AI_HOME_IMG = `${__APP_ENV__.BASE_URL || ''}/assets/channel/ai-home.png`;

/**
 * 应用对话主区空状态：居中插画 + 提示文案，「开始新对话」可点击跳转新会话。
 */
export function ChatEmptyState({ onNewChat }: ChatEmptyStateProps) {
  const localize = useLocalize();
  return (
    <div className="flex h-full min-h-0 w-full flex-col items-center justify-center px-4 text-center">
      <img
        src={AI_HOME_IMG}
        alt=""
        className="mb-[22px] h-20 w-20 object-contain"
      />
      <p className="max-w-[280px] text-[14px] leading-[22px] text-[#86909c]">
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
