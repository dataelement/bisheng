import { X } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useRecoilValue } from 'recoil';
import AppAvator from '~/components/Avator';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize } from '~/hooks';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { AppSidebarConvoItem } from '~/pages/appChat/components/AppSidebarConvoItem';
import { currentChatState } from '~/pages/appChat/store/atoms';
import { cn } from '~/utils';
import { GuestConvoItem } from './components/GuestConvoItem';
import type { useStandaloneSidebar } from './hooks/useStandaloneSidebar';
import { useStandaloneChatContext } from './StandaloneChatContext';

function formatConversationTimeGroupLabel(label: string, localize: (key: string) => string) {
  return label.startsWith('com_ui_date_') || label.startsWith('com_') ? localize(label) : label;
}

function TruncatedLineTooltip({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [truncated, setTruncated] = useState(false);

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setTruncated(el.scrollWidth > el.clientWidth + 1);
  }, []);

  useLayoutEffect(() => {
    measure();
  }, [text, measure]);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);

  const pClassName = cn(className, truncated && 'cursor-default');

  if (!truncated) {
    return <p ref={ref} className={pClassName}>{text}</p>;
  }

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <p ref={ref} className={pClassName}>{text}</p>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="start" className="max-w-[200px]">
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

interface StandaloneSideNavProps {
  sidebar: ReturnType<typeof useStandaloneSidebar>;
  onCloseSidebar?: () => void;
}

export function StandaloneSideNav({ sidebar, onCloseSidebar }: StandaloneSideNavProps) {
  const localize = useLocalize();
  const { data: bsConfig } = useGetBsConfig();
  const { mode } = useStandaloneChatContext();
  const chatState = useRecoilValue(currentChatState);
  const isGuest = mode === 'guest';

  const {
    groups,
    activeChatId,
    switchConversation,
    createNewChat,
    renameConversation,
    deleteConversation,
    fetchConversations,
    currentApp,
  } = sidebar;

  const flowData = chatState?.flow ?? currentApp;
  // Author name may or may not be on the flow response depending on BE version;
  // fall back through common shapes before giving up.
  const authorName =
    (flowData as any)?.user_name ||
    (flowData as any)?.create_user_name ||
    (flowData as any)?.user_id ||
    '';

  return (
    <div className="relative w-[280px] h-full bg-white border-r border-[#ececec] flex flex-col gap-4 overflow-hidden pl-3 pr-2 pt-3 pb-2 text-[#212121]">
      {bsConfig?.sidebarIcon?.image ? (
        <img
          src={__APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image}
          alt="logo"
          className="absolute left-3 top-3 z-20 hidden size-6 object-contain max-[768px]:block"
        />
      ) : null}
      <button
        type="button"
        onClick={onCloseSidebar}
        className={cn(
          'absolute right-3 top-3 z-20 hidden shrink-0 items-center justify-center size-[28px] rounded-[6px] hover:bg-[#f7f8fa] transition-colors',
          onCloseSidebar ? 'max-[768px]:flex' : '',
        )}
        aria-label={localize('com_nav_close_sidebar')}
      >
        <X size={16} className="text-[#4E5969]" />
      </button>
      {/* App card */}
      <div className="shrink-0 pt-8">
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <div
                className="border-[#ebecf0] border-[0.5px] rounded-[6px] p-[8px] flex flex-col gap-[12px] cursor-default"
                style={{ backgroundImage: 'linear-gradient(128.789deg, rgb(249, 251, 254) 0%, rgb(255, 255, 255) 50%, rgb(249, 251, 254) 100%)' }}
              >
                <div className="flex items-center gap-[8px]">
                  <AppAvator
                    className="size-[32px] min-w-[32px] rounded-[4px]"
                    url={flowData?.logo}
                    id={flowData?.id as any}
                    flowType={String(flowData?.flow_type || 5)}
                    iconClassName="w-5 h-5"
                  />
                  <div className="flex-1 flex flex-col min-w-0 justify-center">
                    <h3 className="text-[14px] font-medium leading-[22px] truncate">
                      {flowData?.name || ''}
                    </h3>
                    <TruncatedLineTooltip
                      text={flowData?.description || ''}
                      className="text-[12px] text-[#a9aeb8] leading-[19.5px] truncate"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-center gap-[4px]">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      createNewChat();
                    }}
                    type="button"
                    className="flex-1 min-w-0 h-[28px] flex items-center justify-center gap-1 bg-white border border-[#ececec] rounded-[6px] text-[14px] leading-[22px] hover:bg-gray-50 transition-colors"
                  >
                    {localize('com_knowledge_start_new_chat')}
                  </button>
                </div>
              </div>
            </TooltipTrigger>
            {(flowData?.name || flowData?.description || authorName) && (
              <TooltipContent side="right" align="start" className="max-w-[320px] p-3">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <AppAvator
                      className="size-[32px] min-w-[32px] rounded-[4px]"
                      url={flowData?.logo}
                      id={flowData?.id as any}
                      flowType={String(flowData?.flow_type || 5)}
                      iconClassName="w-5 h-5"
                    />
                    <h4 className="text-[14px] font-semibold leading-[20px] break-all">
                      {flowData?.name || ''}
                    </h4>
                  </div>
                  {flowData?.description && (
                    <p className="text-[12px] leading-[18px] text-[#4e5969] whitespace-pre-wrap break-words">
                      {flowData.description}
                    </p>
                  )}
                  {authorName && (
                    <p className="text-[12px] leading-[18px] text-[#86909c]">
                      {localize('com_app_chat_author')}: {authorName}
                    </p>
                  )}
                </div>
              </TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto pb-[20px] flex flex-col min-h-0">
        {groups.length === 0 ? (
          <div className="flex flex-1 items-center justify-center min-h-[120px] px-3 py-6">
            <p className="text-center text-[14px] leading-[19.5px] text-[#86909c]">
              {localize('com_app_chat_sidebar_empty')}
            </p>
          </div>
        ) : (
          groups.map((group, groupIdx) => (
            <div key={groupIdx} className="flex flex-col">
              <div className="text-black opacity-60 px-[12px] pt-4 text-[12px] mb-1">
                {formatConversationTimeGroupLabel(group.label, localize)}
              </div>
              <div className="flex flex-col">
                {group.conversations.map((conv) => {
                  const isActive = conv.id === activeChatId;

                  if (isGuest) {
                    return (
                      <GuestConvoItem
                        key={conv.id}
                        conv={conv}
                        isActive={isActive}
                        onClick={() => switchConversation(conv)}
                        onRename={renameConversation}
                        onDelete={deleteConversation}
                      />
                    );
                  }

                  return (
                    <AppSidebarConvoItem
                      key={conv.id}
                      conv={conv}
                      isActive={isActive}
                      onClick={() => switchConversation(conv)}
                      onRenameSuccess={() => fetchConversations()}
                      onDeleteSuccess={async () => {
                        const list = await fetchConversations();
                        if (!isActive) return;
                        if (list.length > 0) {
                          switchConversation(list[0]);
                        }
                      }}
                    />
                  );
                })}
              </div>
              <div style={{ marginTop: '5px', marginBottom: '5px' }} />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
