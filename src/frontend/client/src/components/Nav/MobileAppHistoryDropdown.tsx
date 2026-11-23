import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { useLocalize } from '~/hooks';
import { useAppSidebar } from '~/pages/appChat/hooks/useAppSidebar';
import { AppInfoCard } from '~/pages/appChat/components/AppInfoCard';
import { AppSidebarConvoItem } from '~/pages/appChat/components/AppSidebarConvoItem';
import { currentChatState } from '~/pages/appChat/store/atoms';
import { useRecoilValue } from 'recoil';

interface MobileAppHistoryDropdownProps {
    open: boolean;
    onClose: () => void;
    /** Top offset so the panel anchors right under the H5 title bar. */
    topOffset?: string;
}

function formatConversationTimeGroupLabel(label: string, localize: (key: string) => string) {
    return label.startsWith('com_ui_date_') || label.startsWith('com_') ? localize(label) : label;
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

    const historyTrigger = useRef<Element | null>(null);
    useEffect(() => {
        historyTrigger.current = open ? document.activeElement : null;
    }, [open]);

    useEffect(() => {
        if (!open) return;
        const trigger = historyTrigger.current;
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape' && !event.defaultPrevented) {
                event.preventDefault();
                onClose();
                if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
            }
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [open, onClose]);

    if (!open || typeof document === 'undefined') return null;

    // This history region keeps the header and desktop sidebar interactive. Body
    // portals with modal semantics are expanded to the native window by the host.
    return createPortal(
        <div
            className="fixed inset-x-0 bottom-0 z-[80] flex flex-col bg-bg-page"
            style={{ top: topOffset }}
            role="region"
            aria-label={localize('com_app_chat_sidebar_title')}
        >
            <div className="shrink-0 px-3 pt-3">
                <AppInfoCard
                    app={flowData}
                    onShare={shareApp}
                    onNewChat={() => {
                        createNewChat();
                        onClose();
                    }}
                />
            </div>

            {/* Conversation list */}
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-[max(12px,env(safe-area-inset-bottom))] pt-3">
                {groups.length === 0 ? (
                    <div className="flex flex-1 items-center justify-center px-0 py-6">
                        <p className="text-center text-[14px] leading-[19.5px] text-text-3">
                            {localize('com_app_chat_sidebar_empty')}
                        </p>
                    </div>
                ) : (
                    groups.map((group, groupIdx) => (
                        <div key={groupIdx} className="flex flex-col">
                            <div className="mb-1 pt-4 text-caption text-text-3">
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
