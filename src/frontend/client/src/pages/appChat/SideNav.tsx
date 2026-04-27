import { ChevronLeft } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useSetRecoilState, useRecoilValue } from 'recoil';
import AppAvator from '~/components/Avator';
import { MobileSidebarHeaderTabs } from '~/components/Nav/MobileSidebarHeaderTabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize, usePrefersMobileLayout } from '~/hooks';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { UserPopMenu } from '~/layouts/UserPopMenu';
import { AppSidebarConvoItem } from '~/pages/appChat/components/AppSidebarConvoItem';
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

export function SideNav() {
    const location = useLocation();
    const navigate = useNavigate();
    const { conversationId, fid: flowId, type: flowType } = useParams();
    const appOriginStorageKey = (id: string) => `app-chat-origin:${id}`;
    const handleGoBack = () => {
        let fromHomeEntry = false;
        if (conversationId) {
            try {
                fromHomeEntry = sessionStorage.getItem(`app-chat-entry:${conversationId}`) === 'home';
            } catch {
                // ignore storage failures
            }
        }
        const searchParams = new URLSearchParams(location.search);
        const from = searchParams.get('from');
        const entry = searchParams.get('entry');
        let persistedOrigin: 'center' | 'explore' | 'home' | null = null;
        if (conversationId) {
            try {
                const origin = sessionStorage.getItem(appOriginStorageKey(conversationId));
                if (origin === 'center' || origin === 'explore' || origin === 'home') {
                    persistedOrigin = origin;
                }
            } catch {
                // ignore storage failures
            }
        }
        // App center entries (home list / explore) should always return to app center.
        if (from === 'center' || from === 'explore' || persistedOrigin === 'center' || persistedOrigin === 'explore') {
            navigate('/apps');
            return;
        }
        if (fromHomeEntry || (from === 'home-recommended' && entry === 'home') || persistedOrigin === 'home') {
            navigate('/c/new');
            return;
        }
        navigate('/apps');
    };

    const localize = useLocalize();
    const isTabletOrMobile = usePrefersMobileLayout();
    const setSidebarVisible = useSetRecoilState(sidebarVisibleState);
    const { data: bsConfig } = useGetBsConfig();

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
        <div
            className={cn(
                "relative h-full w-full overflow-hidden bg-white text-[#212121] flex flex-col",
                isTabletOrMobile
                    ? "border-r-0 px-0 pb-0 pt-0 gap-0"
                    : "border-r border-[#e5e6eb] px-2 pb-2 pt-2 gap-4",
            )}
        >
            <div className="hidden touch-mobile:block">
                <MobileSidebarHeaderTabs
                    logoSrc={bsConfig?.sidebarIcon?.image ? __APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image : undefined}
                    onClose={() => setSidebarVisible(false)}
                    onLinkClick={(link) => {
                        if (link.closeDrawerOnNavigate) setSidebarVisible(false);
                    }}
                />
            </div>

            {/* PC: back + title — original desktop sidebar chrome */}
            <div className="hidden touch-desktop:flex shrink-0 items-center gap-2">
                <button
                    type="button"
                    onClick={handleGoBack}
                    className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-[#ebecf0] bg-white text-[#212121] transition-colors fine-pointer:hover:bg-[#f7f8fa]"
                    aria-label={localize('com_ui_go_back')}
                >
                    <ChevronLeft size={16} className="shrink-0" />
                </button>
                <span className="min-w-0 truncate text-[14px] font-medium leading-[22px] text-[#212121]">
                    {localize('com_app_chat_sidebar_title')}
                </span>
            </div>

            {/* App card — 应用内对话侧栏固定展示 */}
            <div className="shrink-0 touch-mobile:px-3 touch-mobile:pt-4 touch-mobile:pb-6">
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
                                className="flex h-[28px] min-w-0 flex-1 items-center justify-center gap-1 rounded-[6px] border border-[#ececec] bg-white text-[14px] leading-[22px] transition-colors fine-pointer:hover:bg-gray-50 touch-mobile:px-2"
                            >
                                {localize('com_app_share_app')}
                            </button>
                        ) : null}
                        <button
                            onClick={createNewChat}
                            type="button"
                            className={`min-w-0 h-[28px] flex items-center justify-center gap-1 bg-white border border-[#ececec] rounded-[6px] text-[14px] leading-[22px] transition-colors fine-pointer:hover:bg-gray-50 max-[576px]:px-2 ${showShareApp ? 'flex-1' : 'w-full'}`}
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
                    'touch-mobile:pt-3',
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
                                            onClick={() => {
                                                switchConversation(conv);
                                                if (isTabletOrMobile) {
                                                    setSidebarVisible(false);
                                                }
                                            }}
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

            {/* Footer user panel: mobile only (<768px) */}
            <div className="shrink-0 border-t border-[#ececec] px-2 pb-2 pt-1 hidden max-[768px]:block">
                <UserPopMenu variant="drawer" />
            </div>
        </div>
    );
}