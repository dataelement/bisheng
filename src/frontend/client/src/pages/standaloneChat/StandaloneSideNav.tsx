import { X } from 'lucide-react';
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

  return (
    <div className="relative w-[240px] h-full bg-white border-r border-[#ececec] flex flex-col gap-4 overflow-hidden py-5 px-3 text-[#212121]">
      <div className="hidden shrink-0 items-center justify-between max-[768px]:flex">
        {bsConfig?.sidebarIcon?.image ? (
          <img
            src={__APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image}
            alt="logo"
            className="size-8 rounded-md object-contain"
          />
        ) : (
          <div className="size-8 rounded-md bg-[#F2F3F5]" />
        )}
        <button
          type="button"
          onClick={onCloseSidebar}
          className={cn(
            'inline-flex size-8 shrink-0 items-center justify-center rounded-md text-[#4E5969] transition-colors hover:bg-[#f7f8fa]',
            onCloseSidebar ? '' : 'pointer-events-none opacity-0',
          )}
          aria-label={localize('com_nav_close_sidebar')}
        >
          <X size={16} className="text-[#4E5969]" />
        </button>
      </div>
      {/* App card：仅保留右侧大块 Tooltip；勿再套描述行的小 Tooltip（会与外层叠两层） */}
      <div className="shrink-0 pt-1">
        {flowData?.name || flowData?.description ? (
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div
                  className="border-[#ebecf0] border-[0.5px] rounded-[6px] p-[8px] flex flex-col gap-[12px] cursor-default"
                  style={{ backgroundImage: 'linear-gradient(128.789deg, rgb(var(--brand-500)/0.04) 0%, rgb(255, 255, 255) 50%, rgb(var(--brand-500)/0.04) 100%)' }}
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
                      <p className="text-[12px] text-[#a9aeb8] leading-[19.5px] truncate">
                        {flowData?.description || ''}
                      </p>
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
              <TooltipContent
                side="right"
                align="start"
                noArrow={isGuest}
                sideOffset={isGuest ? 8 : 0}
                className={cn(
                  isGuest
                    ? 'max-w-[min(100vw-2rem,320px)] !rounded-[20px] !border !border-[#E5E6EB] !bg-white !p-5 !text-sm !font-normal !leading-normal !text-[#1D2129] !shadow-[0_8px_32px_rgba(0,0,0,0.12)]'
                    : 'max-w-[320px] p-3',
                )}
              >
                {isGuest ? (
                  <div className="flex flex-col gap-4 text-left text-[#1D2129]">
                    {flowData?.name ? (
                      <div>
                        <p className="mb-1.5 text-[12px] leading-[18px] text-[#86909C]">
                          {localize('com_standalone_guest_app_name_label')}
                        </p>
                        <p className="break-words text-[16px] font-medium leading-[24px] text-[#1D2129]">
                          {flowData.name}
                        </p>
                      </div>
                    ) : null}
                    {flowData?.description ? (
                      <div>
                        <p className="mb-1.5 text-[12px] leading-[18px] text-[#86909C]">
                          {localize('com_standalone_guest_desc_label')}
                        </p>
                        <p className="whitespace-pre-wrap break-words text-[14px] leading-[22px] text-[#1D2129]">
                          {flowData.description}
                        </p>
                      </div>
                    ) : null}
                  </div>
                ) : (
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
                  </div>
                )}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <div
            className="border-[#ebecf0] border-[0.5px] rounded-[6px] p-[8px] flex flex-col gap-[12px] cursor-default"
            style={{ backgroundImage: 'linear-gradient(128.789deg, rgb(var(--brand-500)/0.04) 0%, rgb(255, 255, 255) 50%, rgb(var(--brand-500)/0.04) 100%)' }}
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
                <p className="text-[12px] text-[#a9aeb8] leading-[19.5px] truncate">
                  {flowData?.description || ''}
                </p>
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
        )}
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto pb-[20px] flex flex-col min-h-0 px-2">
        {groups.length === 0 ? (
          <div className="flex flex-1 items-center justify-center min-h-[120px] px-0 py-6">
            <p className="text-center text-[14px] leading-[19.5px] text-[#86909c]">
              {localize('com_app_chat_sidebar_empty')}
            </p>
          </div>
        ) : (
          groups.map((group, groupIdx) => (
            <div key={groupIdx} className="flex flex-col">
              <div className="text-black opacity-60 pt-4 text-[12px] mb-1">
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
