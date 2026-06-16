import { PanelRight } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useLocalize, useMediaQuery, usePrefersMobileLayout } from '~/hooks';
import ShareChat from '../Share/ShareChat';

const types = {
  1: 'skill',
  5: 'assistant',
  10: 'workflow',
  15: 'workbench_chat'
} as const;

export default function HeaderTitle({ conversation, readOnly, hideShare = false, onOpenWorkspace, hasWorkspaceFiles = false }: {
  conversation?: any;
  readOnly?: boolean;
  hideShare?: boolean;
  onOpenWorkspace?: () => void;
  hasWorkspaceFiles?: boolean;
}) {
  const localize = useLocalize();
  const { pathname } = useLocation();
  const isNarrowViewport = usePrefersMobileLayout();
  const isAppChatRoute = pathname.includes('/app/');
  const isAppChatCompact = useMediaQuery('(max-width: 1023px)');
  const normalizedTitle =
    conversation?.title != null && String(conversation.title).trim() !== ''
      ? String(conversation.title).trim()
      : localize('com_ui_new_chat');
  // Title + share are merged into MobileNav on H5；应用内对话在 768–1023 同样走合并顶栏，避免与 AppRoot 悬浮钮重复一行。
  if (isNarrowViewport || (isAppChatRoute && isAppChatCompact)) {
    return null;
  }

  return (
    <div className="sticky top-0 z-10 flex h-[56px] w-full items-center justify-between bg-white px-4 text-[#212121]">
      {/* Left placeholder to balance the center layout */}
      <div className="flex-1"></div>

      {/* Center Title */}
      <div className="flex-[2] flex justify-center text-[14px] font-medium leading-[22px]">
        <div id="app-title" className="truncate max-w-full text-center">
          {normalizedTitle}
        </div>
      </div>

      {/* Right actions */}
      <div className="flex-1 flex justify-end items-center gap-1">
        {!readOnly && !hideShare && (
          <ShareChat
            type={types[conversation?.flowType as keyof typeof types] ?? 'workbench_chat'}
            flowId={conversation?.flowId}
            chatId={conversation?.conversationId || ''}
          />
        )}
        {/* F035: task-mode workspace entry — opens the drawer of uploaded sources +
            generated deliverables for the latest task turn (ChatView owns the drawer). */}
        {hasWorkspaceFiles && onOpenWorkspace && (
          <button
            type="button"
            onClick={onOpenWorkspace}
            title={localize('com_linsight_workspace')}
            aria-label="workspace"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-gray-600 hover:bg-gray-100"
          >
            <PanelRight size={16} />
          </button>
        )}
      </div>
    </div>
  );
}

