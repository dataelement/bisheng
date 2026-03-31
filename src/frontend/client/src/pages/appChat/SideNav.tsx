import { ChevronLeft, MoreHorizontal } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { currentChatState } from '~/pages/appChat/store/atoms';
import { useAppSidebar } from '~/pages/appChat/hooks/useAppSidebar';
import AppAvator from '~/components/Avator';
import { AppSwitcherDropdown } from '~/pages/appChat/components/AppSwitcherDropdown';
import { AppSidebarConvoItem } from '~/pages/appChat/components/AppSidebarConvoItem';
import { cn } from '~/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';

import TodayItemIcon from '~/components/ui/icon/TodayItem';

export function SideNav() {
    const navigate = useNavigate();

    // Current conversation's app data
    const chatState = useRecoilValue(currentChatState);
    const flowData = chatState?.flow;

    // Sidebar hook for conversation list and actions
    const {
        groups,
        activeConversationId,
        switchConversation,
        createNewChat,
        shareApp,
        fetchConversations,
    } = useAppSidebar();

    return (
        <div className="w-[280px] h-full bg-white border-r border-[#ececec] flex flex-col gap-4 px-3 py-5 overflow-hidden text-[#212121]">
            {/* Top back button */}
            <div className="flex items-center gap-[8px] shrink-0">
                <button
                    onClick={() => navigate('/apps')}
                    className="flex shrink-0 items-center justify-center size-[32px] rounded-[8px] bg-[rgba(255,255,255,0.5)] border border-[#ebecf0] backdrop-blur-[4px] hover:bg-gray-50 transition-colors"
                >
                    <ChevronLeft size={16} className="text-[#212121]" />
                </button>
                <span className="text-[14px] font-medium leading-[22px]">应用对话</span>
            </div>

            {/* App card */}
            <div className="shrink-0">
                <div
                    className="border-[#ebecf0] border-[0.5px] rounded-[6px] p-[8px] flex flex-col gap-[12px]"
                    style={{ backgroundImage: "linear-gradient(128.789deg, rgb(249, 251, 254) 0%, rgb(255, 255, 255) 50%, rgb(249, 251, 254) 100%)" }}
                >
                    <div className="flex items-center gap-[8px]">
                        <AppAvator
                            className="size-[32px] min-w-[32px] rounded-[4px]"
                            url={flowData?.logo}
                            id={flowData?.id as any}
                            flowType={String(flowData?.flow_type || 5)}
                            iconClassName='w-5 h-5'
                        />
                        <div className="flex-1 flex flex-col min-w-0 justify-center">
                            <div className="flex items-center justify-between">
                                <h3 className="text-[14px] font-medium leading-[22px] truncate">
                                    {flowData?.name || '未知应用'}
                                </h3>
                                {/* App switcher dropdown */}
                                <div className="shrink-0 size-[16px] flex items-center justify-center ml-1">
                                    <AppSwitcherDropdown />
                                </div>
                            </div>
                            <TooltipProvider delayDuration={300}>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <p className="text-[12px] text-[#a9aeb8] leading-[19.5px] truncate cursor-default">
                                            {flowData?.description || '暂无描述信息'}
                                        </p>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" align="start" className="max-w-[200px]">
                                        {flowData?.description || '暂无描述信息'}
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        </div>
                    </div>

                    <div className="flex items-center justify-center gap-[4px]">
                        <button
                            onClick={shareApp}
                            className="flex-1 min-w-0 h-[28px] flex items-center justify-center bg-white border border-[#ececec] rounded-[6px] text-[14px] leading-[22px] hover:bg-gray-50 transition-colors"
                        >
                            分享应用
                        </button>
                        <button
                            onClick={createNewChat}
                            className="flex-1 min-w-0 h-[28px] flex items-center justify-center bg-white border border-[#ececec] rounded-[6px] text-[14px] leading-[22px] hover:bg-gray-50 transition-colors"
                        >
                            开启新对话
                        </button>
                    </div>
                </div>
            </div>

            {/* Conversation list */}
            <div className="flex-1 overflow-y-auto pb-[20px] flex flex-col">
                {groups.length === 0 ? (
                    <div className="text-center text-gray-400 text-sm py-10">还没有任何历史对话</div>
                ) : (
                    groups.map((group, groupIdx) => (
                        <div key={groupIdx} className="flex flex-col">
                            {/* Time label */}
                            <div className="text-black opacity-60 px-[12px] pt-4 text-[12px] mb-1">
                                {group.label}
                            </div>
                            {/* Items */}
                            <div className="flex flex-col">
                                {group.conversations.map((conv) => {
                                    const isActive = conv.id === activeConversationId;
                                    return (
                                        <AppSidebarConvoItem
                                            key={conv.id}
                                            conv={conv}
                                            isActive={isActive}
                                            onClick={() => switchConversation(conv)}
                                            onRenameSuccess={() => fetchConversations()}
                                            onDeleteSuccess={() => {
                                                fetchConversations();
                                                if (isActive) {
                                                    createNewChat();
                                                }
                                            }}
                                        />
                                    );
                                })}
                            </div>

                            {/* Spacer */}
                            <div style={{ marginTop: '5px', marginBottom: '5px' }} />
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}