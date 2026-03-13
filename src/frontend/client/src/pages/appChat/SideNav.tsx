import { ChevronLeft, MessageSquare, MoreHorizontal } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { currentChatState } from '~/pages/appChat/store/atoms';
import { useAppSidebar } from '~/pages/appChat/hooks/useAppSidebar';
import AppAvator from '~/components/Avator';
import { AppSwitcherDropdown } from '~/pages/appChat/components/AppSwitcherDropdown';
import { cn } from '~/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';

export function SideNav() {
    const navigate = useNavigate();
    
    // 获取当前对话的应用数据
    const chatState = useRecoilValue(currentChatState);
    const flowData = chatState?.flow;
    
    // 从 sidebar hook 中获取会话列表及操作方法
    const {
        groups,
        activeConversationId,
        switchConversation,
        createNewChat,
        shareApp,
    } = useAppSidebar();

    return (
        <div className="w-full h-full bg-white border-r border-[#ececec] flex flex-col overflow-hidden text-[#212121]">
            {/* 顶部返回区域 */}
            <div className="flex items-center gap-[8px] px-[12px] py-[20px] shrink-0">
                <button 
                    onClick={() => navigate('/apps')}
                    className="flex shrink-0 items-center justify-center size-[32px] rounded-[8px] bg-[rgba(255,255,255,0.5)] border border-[#ebecf0] backdrop-blur-[4px] hover:bg-gray-50 transition-colors"
                >
                    <ChevronLeft size={16} className="text-[#212121]" />
                </button>
                <span className="text-[14px] font-medium leading-[22px]">应用对话</span>
            </div>

            {/* 应用卡片区域 */}
            <div className="px-[12px] mb-[16px] shrink-0">
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
                        />
                        <div className="flex-1 flex flex-col min-w-0 justify-center">
                            <div className="flex items-center justify-between">
                                <h3 className="text-[14px] font-medium leading-[22px] truncate">
                                    {flowData?.name || '未知应用'}
                                </h3>
                                {/* 切换应用下拉 */}
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

            {/* 会话列表区域 */}
            <div className="flex-1 px-[12px] overflow-y-auto pb-[20px] flex flex-col gap-[16px]">
                {groups.length === 0 ? (
                    <div className="text-center text-gray-400 text-sm py-10">暂无对话记录</div>
                ) : (
                    groups.map((group, groupIdx) => (
                        <div key={groupIdx} className="flex flex-col gap-[4px]">
                            {/* 时间标签 */}
                            <div className="px-[12px] py-[4px]">
                                <span className="opacity-60 text-[12px] leading-normal">{group.label}</span>
                            </div>
                            {/* 列表内容 */}
                            <div className="flex flex-col gap-[4px]">
                                {group.conversations.map((conv) => {
                                    const isActive = conv.id === activeConversationId;
                                    return (
                                        <div
                                            key={conv.id}
                                            onClick={() => switchConversation(conv)}
                                            className={cn(
                                                "group flex items-center gap-[8px] px-[12px] py-[6px] rounded-[8px] cursor-pointer transition-colors relative",
                                                isActive ? "bg-[#f7f7f7]" : "hover:bg-[#f7f7f7]"
                                            )}
                                        >
                                            <div className="shrink-0 size-[24px] flex items-center justify-center text-gray-400">
                                                <MessageSquare size={16} />
                                            </div>
                                            <div className="flex-1 min-w-0 flex flex-col justify-center">
                                                <p className="text-[14px] leading-[20px] truncate">{conv.title}</p>
                                            </div>
                                            
                                            {/* TODO: 删除对话、重命名等操作，可以放置在这里 */}
                                            {/* <div className={cn(
                                                "absolute right-2 shrink-0 p-1 opacity-0 transition-opacity",
                                                isActive ? "opacity-100" : "group-hover:opacity-100"
                                            )}>
                                                <MoreHorizontal size={14} className="text-gray-500 hover:text-gray-800" />
                                            </div> */}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}