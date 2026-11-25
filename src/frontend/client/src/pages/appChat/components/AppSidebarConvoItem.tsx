import { useState, useRef, useCallback, useEffect } from 'react';
import { Check, X } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import { Dropdown, DropdownItem, DropdownSeparator } from '@bisheng/ui';
import type { MouseEvent, FocusEvent, KeyboardEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSetRecoilState } from 'recoil';

import { useLocalize } from '~/hooks';
import { useToastContext, useConfirm } from '~/Providers';
import { ConversationHistoryDate } from '~/components/Conversations/ConversationHistoryDate';
import { SIDEBAR_ICON_BUTTON_CLASS_NAME } from '~/layouts/WorkbenchSidebar/sidebarIconButton';
import { cn } from '~/utils';
import { useUpdateConversationMutation, useDeleteConversationMutation } from '~/hooks/queries/data-provider';
import type { AppConversation } from '~/@types/app';
import type { TMessage } from '~/types/chat';
import { QueryKeys } from '~/types/chat';
import { chatsState, runningState } from '~/pages/appChat/store/atoms';
import { closeAppChatWebSocket } from '~/pages/appChat/useWebsocket';

import TodayItemIcon from '~/components/ui/icon/TodayItem';
import LingsiIcon from '~/components/ui/icon/Lingsi';

interface AppSidebarConvoItemProps {
    conv: AppConversation;
    isActive: boolean;
    compact?: boolean;
    onClick: () => void;
    onDeleteSuccess: () => void;
    onRenameSuccess?: (conversationId: string, title: string) => void;
}

export function AppSidebarConvoItem({ conv, isActive, compact = false, onClick, onDeleteSuccess, onRenameSuccess }: AppSidebarConvoItemProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    const [isPopoverActive, setIsPopoverActive] = useState(false);
    // Keep the menu anchored to the row through its exit animation.
    const [isPopoverPresent, setIsPopoverPresent] = useState(false);
    const [renaming, setRenaming] = useState(false);
    const [titleInput, setTitleInput] = useState(conv.title);
    const confirm = useConfirm();

    const inputRef = useRef<HTMLInputElement>(null);

    const updateConvoMutation = useUpdateConversationMutation(conv.id);
    const setChats = useSetRecoilState(chatsState);
    const setRunning = useSetRecoilState(runningState);

    // ----- Rename Logic -----
    const handleRenameStart = useCallback((e?: MouseEvent) => {
        e?.preventDefault();
        e?.stopPropagation();
        setIsPopoverActive(false);
        setIsPopoverPresent(false);
        setTitleInput(conv.title);
        setRenaming(true);
    }, [conv.title]);

    useEffect(() => {
        if (renaming && inputRef.current) {
            inputRef.current.focus();
            if (compact) inputRef.current.select();
        }
    }, [compact, renaming]);

    const handleRenameSubmit = useCallback(
        async () => {
            setRenaming(false);
            if (!conv.id || titleInput === conv.title || (compact && !titleInput.trim())) return;

            try {
                const payload = {
                    conversationId: conv.id,
                    title: titleInput,
                    flowId: conv.flowId,
                    flowType: conv.flowType,
                };
                await updateConvoMutation.mutateAsync(payload);
            } catch {
                showToast({ message: localize('com_ui_rename_failed'), status: 'warning' });
                return;
            }
            onRenameSuccess?.(conv.id, titleInput);
        },
        [compact, conv, titleInput, updateConvoMutation, showToast, localize, onRenameSuccess]
    );

    const handleRenameCancel = () => setRenaming(false);

    const handleRenameKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
        if (e.nativeEvent.isComposing) {
            e.stopPropagation();
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            handleRenameCancel();
        } else if (e.key === 'Enter' && e.target === inputRef.current) {
            e.preventDefault();
            e.stopPropagation();
            void handleRenameSubmit();
        }
    };

    const handleRenameBlur = (e: FocusEvent<HTMLDivElement>) => {
        if (!e.currentTarget.contains(e.relatedTarget)) void handleRenameSubmit();
    };

    // ----- Delete Logic -----
    const deleteConvoMutation = useDeleteConversationMutation({
        onSuccess: () => {
            // Tear down any in-flight streaming for this chat: close its WS,
            // drop its session info, and purge Recoil chats / running state.
            // Without this, a delete during streaming leaves the websocket alive
            // and the right pane keeps rendering messages for a deleted convo.
            closeAppChatWebSocket(conv.id);
            setChats((prev) => {
                if (!(conv.id in prev)) return prev;
                const next = { ...prev };
                delete next[conv.id];
                return next;
            });
            setRunning((prev) => {
                if (!(conv.id in prev)) return prev;
                const next = { ...prev };
                delete next[conv.id];
                return next;
            });
            onDeleteSuccess();
        },
    });

    const confirmDelete = useCallback(() => {
        const messages = queryClient.getQueryData<TMessage[]>([QueryKeys.messages, conv.id]);
        const thread_id = messages?.[messages.length - 1]?.thread_id;
        const endpoint = messages?.[messages.length - 1]?.endpoint;

        deleteConvoMutation.mutate({ conversationId: conv.id, thread_id, endpoint, source: 'button' });
    }, [conv.id, deleteConvoMutation, queryClient]);

    const handleDeleteClick = useCallback(async () => {
        const ok = await confirm({
            variant: 'destructive',
            title: localize('com_ui_delete_conversation'),
            description: `${localize('com_ui_delete_confirm')} "${conv.title}"`,
            confirmText: localize('com_ui_delete'),
        });
        if (!ok) {
            return;
        }
        confirmDelete();
    }, [confirm, localize, conv.title, confirmDelete]);

    return (
        <div
            className={cn(
                'group mb-1 flex w-full shrink-0 cursor-pointer items-center gap-2 rounded-lg transition-colors',
                compact ? 'min-h-8 px-2 py-[5px] coarse-pointer:min-h-11 coarse-pointer:py-0' : 'px-[12px] py-[6px]',
                isActive ? (compact ? 'bg-fill-2' : 'bg-[#EEE]') : 'hover:bg-fill-1',
                // Pin the hover fill while the row owns a transient UI — an open
                // options menu or the rename input — since the pointer leaves the
                // row (into the portaled menu) long before the interaction is over.
                // Never promoted to the active row's fill: this row is not the open
                // conversation. Applies on coarse pointers too, where it reads as
                // "this row owns the menu" rather than as a hover affordance.
                !isActive && (renaming || isPopoverActive || isPopoverPresent) && 'bg-fill-1',
                compact && renaming && 'ring-1 ring-inset ring-border-base',
            )}
            onClick={() => {
                if (renaming) return;
                // prevent switching if we click dropdown
                if (isPopoverActive) return;
                onClick();
            }}
        >
            {renaming ? (
                <div
                    className={cn('flex min-w-0 grow items-center gap-2', !compact && 'h-6 overflow-hidden')}
                    onBlur={compact ? handleRenameBlur : undefined}
                    onKeyDown={handleRenameKeyDown}
                    onClick={(e) => e.stopPropagation()}
                >
                    <input
                        ref={inputRef}
                        type="text"
                        className={cn(
                            'min-w-0 grow rounded-sm text-text-1 focus-visible:outline-none',
                            compact ? 'bg-transparent text-body' : 'bg-white px-1 text-[14px] leading-tight',
                        )}
                        aria-label={`${localize('com_ui_rename')} ${localize('com_ui_chat')}`}
                        value={titleInput}
                        onChange={(e) => setTitleInput(e.target.value)}
                    />
                    <div className="flex gap-1 shrink-0">
                        {!compact && (
                            <button type="button" onClick={handleRenameCancel} aria-label={localize('com_ui_cancel')}>
                                <X className="h-4 w-4 text-text-2 transition-colors duration-200 ease-in-out fine-pointer:hover:opacity-70" />
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={handleRenameSubmit}
                            className={compact ? 'flex size-4 items-center justify-center coarse-pointer:size-11' : undefined}
                            aria-label={`${localize('com_ui_submit')} ${localize('com_ui_rename')}`}
                        >
                            {compact ? (
                                <Outlined.Check size={12} aria-hidden className="transition-colors hover:opacity-70" />
                            ) : (
                                <Check className="h-4 w-4 text-blue-500 transition-colors duration-200 ease-in-out fine-pointer:hover:opacity-70" />
                            )}
                        </button>
                    </div>
                </div>
            ) : compact ? (
                <button
                    type="button"
                    aria-current={isActive ? 'page' : undefined}
                    className="min-w-0 grow cursor-pointer truncate rounded-sm text-left text-body text-text-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 coarse-pointer:min-h-11"
                    onDoubleClick={handleRenameStart}
                    title={conv.title}
                >
                    {conv.title}
                </button>
            ) : (
                <div
                    className="flex grow items-center gap-[8px] overflow-hidden whitespace-nowrap break-all"
                    onDoubleClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        handleRenameStart();
                    }}
                >
                    {conv.flowType === 20 ? (
                        <LingsiIcon className="size-[24px] shrink-0" />
                    ) : (
                        <TodayItemIcon className="size-[24px] shrink-0 text-[#6B778D]" />
                    )}
                    <span className="text-text-1 text-[14px] leading-[20px] font-['PingFang_SC:Regular',sans-serif] truncate">
                        {conv.title}
                    </span>
                </div>
            )}

            {!renaming && (
                <div className={cn(
                    'shrink-0',
                    compact ? 'grid items-center justify-items-end' : 'coarse-pointer:flex',
                    !compact && (isPopoverActive || isActive ? 'flex' : 'hidden group-focus-within:flex group-hover:flex'),
                )}>
                    {compact && (
                        <ConversationHistoryDate
                            updatedAt={conv.updatedAt}
                            createdAt={conv.createdAt}
                            className={cn(
                                'col-start-1 row-start-1 whitespace-nowrap text-caption-sm text-text-3 group-hover:invisible group-has-[:focus-visible]:invisible coarse-pointer:hidden',
                                isPopoverPresent && 'invisible',
                            )}
                        />
                    )}
                    <div
                        className={cn(
                            compact && 'col-start-1 row-start-1 flex',
                            // Keep the trigger in the tab order and measurable while hidden.
                            compact && !isPopoverPresent && 'pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 group-has-[:focus-visible]:pointer-events-auto group-has-[:focus-visible]:opacity-100 coarse-pointer:pointer-events-auto coarse-pointer:opacity-100',
                        )}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <Dropdown
                            align="end"
                            open={isPopoverActive}
                            onOpenChange={(open) => {
                                setIsPopoverActive(open);
                                if (compact && open) setIsPopoverPresent(true);
                            }}
                            onCloseAutoFocus={() => setIsPopoverPresent(false)}
                            menu={
                                <>
                                    <DropdownItem icon={<Outlined.Edit />} onSelect={() => handleRenameStart()}>
                                        {localize('com_ui_rename')}
                                    </DropdownItem>
                                    <DropdownSeparator />
                                    <DropdownItem
                                        danger
                                        icon={<Outlined.Delete />}
                                        onSelect={() => {
                                            setIsPopoverActive(false);
                                            handleDeleteClick();
                                        }}
                                    >
                                        {localize('com_ui_delete')}
                                    </DropdownItem>
                                </>
                            }
                        >
                            <button
                                type="button"
                                className={compact
                                    ? cn(SIDEBAR_ICON_BUTTON_CLASS_NAME, 'coarse-pointer:size-11')
                                    : 'flex size-7 shrink-0 items-center justify-center rounded-md text-text-2 transition-colors hover:bg-black/5'
                                }
                                aria-label={localize('com_nav_convo_menu_options')}
                            >
                                <Outlined.More className="size-4" aria-hidden />
                            </button>
                        </Dropdown>
                    </div>
                </div>
            )}
        </div>
    );
}
