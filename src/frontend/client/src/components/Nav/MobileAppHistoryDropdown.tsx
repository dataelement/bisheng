import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import AppAvator from '~/components/Avator';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize } from '~/hooks';
import { useAppSidebar } from '~/pages/appChat/hooks/useAppSidebar';
import { AppSidebarConvoItem } from '~/pages/appChat/components/AppSidebarConvoItem';
import { AppSwitcherDropdown } from '~/pages/appChat/components/AppSwitcherDropdown';
import { currentChatState } from '~/pages/appChat/store/atoms';
import { useRecoilValue } from 'recoil';
import { cn } from '~/utils';

interface MobileAppHistoryDropdownProps {
    open: boolean;
    onClose: () => void;
    /** Top offset so the panel anchors right under the H5 title bar. */
    topOffset?: string;
}

function formatConversationTimeGroupLabel(label: string, localize: (key: string) => string) {
    return label.startsWith('com_ui_date_') || label.startsWith('com_') ? localize(label) : label;
}

/** Only show the full text tooltip when the truncated text actually overflows. */
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

/**
 * H5 app-chat history dropdown — anchored under MobileNav's title row when in /app/* surface.
 *
 * Replaces the old right-side sidebar drawer on mobile: same data hook (`useAppSidebar`),
 * same app card + grouped conversation list, just laid out as a portal dropdown matching
 * the channel / knowledge / main-chat dropdowns.
 */
export function MobileAppHistoryDropdown({
    open,
    onClose,
    topOffset = 'calc(env(safe-area-inset-top, 0px) + 52px)',
}: MobileAppHistoryDropdownProps) {
    const localize = useLocalize();
    const location = useLocation();
    const navigate = useNavigate();
    const { fid: flowId, type: flowType } = useParams();
    const {
        groups,
        activeConversationId,
        switchConversation,
        createNewChat,
        shareApp,
        fetchConversations,
        currentApp,
    } = useAppSidebar();
    const chatState = useRecoilValue(currentChatState);

    // Same fallback as SideNav: prefer the live chat's flow, fall back to currentApp.
    const flowData = chatState?.flow ?? currentApp;
    const showShareApp = flowData?.can_share === true;

    if (!open || typeof document === 'undefined') return null;

    // Render through a portal so the dropdown escapes MobileNav's stacking context (its
    // sibling holds chat content + input form which would otherwise paint on top).
    return createPortal(
        <div
            className="fixed inset-x-0 bottom-0 z-[80] flex flex-col bg-white"
            style={{ top: topOffset }}
            role="dialog"
            aria-modal="true"
            aria-label={localize('com_app_chat_sidebar_title')}
        >
            {/* App card — same UI as the SideNav card */}
            <div className="shrink-0 px-3 pt-3">
                <div
                    className="flex flex-col gap-3 rounded-[6px] border-[0.5px] border-[#ebecf0] p-2"
                    style={{
                        backgroundImage:
                            'linear-gradient(128.789deg, rgb(var(--brand-500)/0.04) 0%, rgb(255, 255, 255) 50%, rgb(var(--brand-500)/0.04) 100%)',
                    }}
                >
                    <div className="flex items-center gap-2">
                        <AppAvator
                            className="size-[32px] min-w-[32px] rounded-[4px]"
                            url={flowData?.logo}
                            id={flowData?.id as any}
                            flowType={String(flowData?.flow_type || 5)}
                            iconClassName="w-5 h-5"
                        />
                        <div className="flex min-w-0 flex-1 flex-col justify-center">
                            <div className="flex items-center justify-between">
                                <h3 className="truncate text-[14px] font-medium leading-[22px]">
                                    {flowData?.name || '未知应用'}
                                </h3>
                                <div className="ml-1 flex size-[16px] shrink-0 items-center justify-center">
                                    <AppSwitcherDropdown />
                                </div>
                            </div>
                            <TruncatedLineTooltip
                                text={flowData?.description || '暂无描述信息'}
                                className="truncate text-[12px] leading-[19.5px] text-[#a9aeb8]"
                            />
                        </div>
                    </div>
                    <div className="flex items-center justify-center gap-1">
                        {showShareApp ? (
                            <button
                                type="button"
                                onClick={() => {
                                    shareApp();
                                }}
                                className="flex h-[28px] min-w-0 flex-1 items-center justify-center gap-1 rounded-[6px] border border-[#ececec] bg-white px-2 text-[14px] leading-[22px] transition-colors fine-pointer:hover:bg-gray-50"
                            >
                                {localize('com_app_share_app')}
                            </button>
                        ) : null}
                        <button
                            type="button"
                            onClick={() => {
                                createNewChat();
                                onClose();
                            }}
                            className={cn(
                                'flex h-[28px] min-w-0 items-center justify-center gap-1 rounded-[6px] border border-[#ececec] bg-white px-2 text-[14px] leading-[22px] transition-colors fine-pointer:hover:bg-gray-50',
                                showShareApp ? 'flex-1' : 'w-full',
                            )}
                        >
                            {localize('com_knowledge_start_new_chat')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Conversation list */}
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-[max(12px,env(safe-area-inset-bottom))] pt-3">
                {groups.length === 0 ? (
                    <div className="flex flex-1 items-center justify-center px-0 py-6">
                        <p className="text-center text-[14px] leading-[19.5px] text-[#86909c]">
                            {localize('com_app_chat_sidebar_empty')}
                        </p>
                    </div>
                ) : (
                    groups.map((group, groupIdx) => (
                        <div key={groupIdx} className="flex flex-col">
                            <div className="mb-1 pt-4 text-[12px] text-black opacity-60">
                                {formatConversationTimeGroupLabel(group.label, localize)}
                            </div>
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
                                                onClose();
                                            }}
                                            onRenameSuccess={() => fetchConversations()}
                                            onDeleteSuccess={async () => {
                                                const list = await fetchConversations();
                                                if (!isActive) return;
                                                if (list.length > 0) {
                                                    switchConversation(list[0]);
                                                } else if (flowId && flowType) {
                                                    navigate(`/app/${flowId}/${flowType}`, {
                                                        state: {
                                                            ...(location.state as object | null),
                                                            fromDelete: true,
                                                        },
                                                    });
                                                    onClose();
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
        </div>,
        document.body,
    );
}
