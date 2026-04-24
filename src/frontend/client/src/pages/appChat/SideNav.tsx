import { ChevronLeft, X } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useSetRecoilState, useRecoilValue } from 'recoil';
import AppAvator from '~/components/Avator';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize } from '~/hooks';
import { AppSidebarConvoItem } from '~/pages/appChat/components/AppSidebarConvoItem';
import { SideNavModuleTabs } from '~/pages/appChat/components/SideNavModuleTabs';
import { AppSwitcherDropdown } from '~/pages/appChat/components/AppSwitcherDropdown';
import { useAppSidebar } from '~/pages/appChat/hooks/useAppSidebar';
import { sidebarVisibleState } from '~/pages/appChat/store/appSidebarAtoms';
import { currentChatState } from '~/pages/appChat/store/atoms';
import { cn } from '~/utils';

function formatConversationTimeGroupLabel(label: string, localize: (key: string) => string) {
    return label.startsWith('com_ui_date_') || label.startsWith('com_') ? localize(label) : label;
}

/** 仅当单行 truncate 实际溢出时显示完整文案的 Tooltip */
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
        return (
            <p ref={ref} className={pClassName}>
                {text}
            </p>
        );
    }

    return (
        <TooltipProvider delayDuration={300}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <p ref={ref} className={pClassName}>
                        {text}
                    </p>
                </TooltipTrigger>
                <TooltipContent side="bottom" align="start" className="max-w-[200px]">
                    {text}
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}

/** 应用中心 / 探索广场进入时带 from=center|explore；分享链接等无此参数 — H5 侧栏不展示四大模块 Tab */
function useShowMobileHubTabs() {
    const { search } = useLocation();
    const from = new URLSearchParams(search).get('from');
    return from === 'center' || from === 'explore';
}

export function SideNav() {
    const navigate = useNavigate();
    const localize = useLocalize();
    const { fid: flowId, type: flowType } = useParams();
    const setSidebarVisible = useSetRecoilState(sidebarVisibleState);
    const showMobileHubTabs = useShowMobileHubTabs();

    // Current conversation's app data
    const chatState = useRecoilValue(currentChatState);

    // Sidebar hook for conversation list and actions
    const {
        groups,
        activeConversationId,
        switchConversation,
        createNewChat,
        shareApp,
        fetchConversations,
        currentApp,
    } = useAppSidebar();

    // Fall back to `currentApp` (populated by AppChatEntry) when no chat is active —
    // e.g. right after deleting the last conversation, chatState is cleared but the
    // sidebar card should still show the app's name / logo / description.
    const flowData = chatState?.flow ?? currentApp;
    const showShareApp = flowData?.can_share === true;

    return (
        <div className="relative w-[280px] h-full bg-white border-r border-[#ececec] flex flex-col gap-4 px-2 py-2 overflow-hidden text-[#212121]">
            {/* H5 overlay: close sidebar — PC uses NavToggle to collapse */}
            <button
                type="button"
                onClick={() => setSidebarVisible(false)}
                className="absolute right-2 top-2 z-20 hidden shrink-0 touch-mobile:flex items-center justify-center size-[28px] rounded-[6px] hover:bg-[#f7f8fa] transition-colors"
                aria-label={localize('com_nav_close_sidebar')}
            >
                <X size={16} className="text-[#4E5969]" />
            </button>

            {/* PC: back + title — original desktop sidebar chrome */}
            <div className="hidden touch-desktop:flex shrink-0 items-center gap-2 pt-1">
                <button
                    type="button"
                    onClick={() => navigate('/apps')}
                    className="flex size-7 shrink-0 items-center justify-center rounded-[6px] text-[#212121] transition-colors hover:bg-[#f7f8fa]"
                    aria-label={localize('com_ui_go_back')}
                >
                    <ChevronLeft className="size-4" />
                </button>
                <span className="min-w-0 truncate text-[14px] font-medium leading-[22px] text-[#212121]">
                    {localize('com_app_chat_sidebar_title')}
                </span>
            </div>

            {/* Top module tabs — H5 仅应用中心/探索进入时展示；分享应用侧栏只保留会话历史等 */}
            {showMobileHubTabs ? (
                <div className="hidden touch-mobile:block pt-8">
                    <SideNavModuleTabs />
                </div>
            ) : null}

            {/* App card — PC 始终展示；H5 仅应用中心/探索进入时展示，分享入口只保留下方会话列表 */}
            <div
                className={cn(
                    'shrink-0',
                    !showMobileHubTabs && 'hidden touch-desktop:block',
                )}
            >
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
                            <TruncatedLineTooltip
                                text={flowData?.description || '暂无描述信息'}
                                className="text-[12px] text-[#a9aeb8] leading-[19.5px] truncate"
                            />
                        </div>
                    </div>

                    <div className="flex items-center justify-center gap-[4px]">
                        {showShareApp ? (
                            <button
                                onClick={shareApp}
                                type="button"
                                className="flex-1 min-w-0 h-[28px] flex items-center justify-center gap-1 bg-white border border-[#ececec] rounded-[6px] text-[14px] leading-[22px] hover:bg-gray-50 transition-colors touch-mobile:px-2"
                            >
                                {localize('com_app_share_app')}
                            </button>
                        ) : null}
                        <button
                            onClick={createNewChat}
                            type="button"
                            className={`min-w-0 h-[28px] flex items-center justify-center gap-1 bg-white border border-[#ececec] rounded-[6px] text-[14px] leading-[22px] hover:bg-gray-50 transition-colors max-[576px]:px-2 ${showShareApp ? 'flex-1' : 'w-full'}`}
                        >
                            {localize('com_knowledge_start_new_chat')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Conversation list */}
            <div
                className={cn(
                    'flex-1 overflow-y-auto pb-[20px] flex flex-col min-h-0',
                    !showMobileHubTabs && 'touch-mobile:pt-8',
                )}
            >
                {groups.length === 0 ? (
                    <div className="flex flex-1 items-center justify-center min-h-[120px] px-3 py-6">
                        <p className="text-center text-[14px] leading-[19.5px] text-[#86909c]">
                            {localize('com_app_chat_sidebar_empty')}
                        </p>
                    </div>
                ) : (
                    groups.map((group, groupIdx) => (
                        <div key={groupIdx} className="flex flex-col">
                            {/* Time label */}
                            <div className="text-black opacity-60 px-[12px] pt-4 text-[12px] mb-1">
                                {formatConversationTimeGroupLabel(group.label, localize)}
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
                                            onDeleteSuccess={async () => {
                                                const list = await fetchConversations();
                                                if (!isActive) return;
                                                if (list.length > 0) {
                                                    // Jump to the now-most-recent conversation
                                                    switchConversation(list[0]);
                                                } else if (flowId && flowType) {
                                                    // Last conversation deleted — land on empty state, don't auto-create
                                                    navigate(`/app/${flowId}/${flowType}`, {
                                                        state: { fromDelete: true },
                                                    });
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