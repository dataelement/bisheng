import { useLocalize, usePrefersMobileLayout } from '~/hooks';
import ShareChat from '../Share/ShareChat';

const types = {
  1: 'skill',
  5: 'assistant',
  10: 'workflow',
  15: 'workbench_chat'
};

export default function HeaderTitle({ conversation, readOnly, hideShare = false }) {
  const localize = useLocalize();
  const isNarrowViewport = usePrefersMobileLayout();

  // Title + share are merged into MobileNav on H5; avoid a second full-width row.
  if (isNarrowViewport) {
    return null;
  }

  return (
    <div className="sticky top-0 z-10 flex h-[56px] w-full items-center justify-between bg-white px-4 border-b border-[#ebecf0] text-[#212121]">
      {/* Left placeholder to balance the center layout */}
      <div className="flex-1"></div>

      {/* Center Title */}
      <div className="flex-[2] flex justify-center text-[14px] font-medium leading-[22px]">
        <div id="app-title" className="truncate max-w-full text-center">
          {conversation?.title || localize('com_ui_new_chat')}
        </div>
      </div>

      {/* Right actions */}
      <div className="flex-1 flex justify-end items-center">
        {!readOnly && !hideShare && (
          <ShareChat 
            type={types[conversation?.flowType as keyof typeof types]} 
            flowId={conversation?.flowId} 
            chatId={conversation?.conversationId || ''} 
          />
        )}
      </div>
    </div>
  );
}

