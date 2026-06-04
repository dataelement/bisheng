import { useState, useRef, useCallback, useEffect } from 'react';
import { Check, X } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import type { MouseEvent, FocusEvent, KeyboardEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { useSetRecoilState } from 'recoil';

import { useLocalize } from '~/hooks';
import { useToastContext } from '~/Providers';
import { cn } from '~/utils';
import { useUpdateConversationMutation, useDeleteConversationMutation } from '~/hooks/queries/data-provider';
import type { AppConversation } from '~/@types/app';
import type { TMessage } from '~/types/chat';
import { QueryKeys } from '~/types/chat';
import { chatsState, runningState } from '~/pages/appChat/store/atoms';
import { closeAppChatWebSocket } from '~/pages/appChat/useWebsocket';

import { OGDialog, Label } from '~/components';
import {
    DropdownMenu,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '~/components/ui/DropdownMenu';
import {
    SidebarListMoreMenuContent,
    sidebarListMoreMenuDangerIconClassName,
    sidebarListMoreMenuDangerItemClassName,
    sidebarListMoreMenuDangerLabelClassName,
    sidebarListMoreMenuIconClassName,
    sidebarListMoreMenuItemClassName,
    sidebarListMoreMenuLabelClassName,
} from '~/components/SidebarListMoreMenu';
import OGDialogTemplate from '~/components/ui/OGDialogTemplate';
import TodayItemIcon from '~/components/ui/icon/TodayItem';
import LingsiIcon from '~/components/ui/icon/Lingsi';

type AppSidebarConvoItemProps = {
    conv: AppConversation;
    isActive: boolean;
    onClick: () => void;
    onDeleteSuccess: () => void;
    onRenameSuccess?: () => void;
};

export function AppSidebarConvoItem({ conv, isActive, onClick, onDeleteSuccess, onRenameSuccess }: AppSidebarConvoItemProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const { fid: flowId, type: flowType, conversationId: currentConvoId } = useParams();

    const [isPopoverActive, setIsPopoverActive] = useState(false);
    const [renaming, setRenaming] = useState(false);
    const [titleInput, setTitleInput] = useState(conv.title);
    const [showDeleteDialog, setShowDeleteDialog] = useState(false);

    const inputRef = useRef<HTMLInputElement>(null);
    const deleteButtonRef = useRef<HTMLButtonElement>(null);

    const updateConvoMutation = useUpdateConversationMutation(currentConvoId ?? '');
    const setChats = useSetRecoilState(chatsState);
    const setRunning = useSetRecoilState(runningState);
    
    // ----- Rename Logic -----
    const handleRenameStart = useCallback((e?: MouseEvent) => {
        e?.preventDefault();
        e?.stopPropagation();
        setIsPopoverActive(false);
        setTitleInput(conv.title);
        setRenaming(true);
    }, [conv.title]);

    useEffect(() => {
        if (renaming && inputRef.current) {
            inputRef.current.focus();
        }
    }, [renaming]);

    const submitRename = useCallback(
        (e: MouseEvent<HTMLButtonElement> | FocusEvent<HTMLInputElement> | KeyboardEvent<HTMLInputElement>) => {
            e.preventDefault();
            e.stopPropagation();
            setRenaming(false);
            if (titleInput === conv.title) return;
            if (!conv.id) return;

            updateConvoMutation.mutate(
                {
                    conversationId: conv.id,
                    title: titleInput ?? '',
                    flowId: conv.flowId,
                    flowType: conv.flowType,
                },
                {
                    onSuccess: () => {
                        onRenameSuccess?.();
                    },
                    onError: () => {
                        setTitleInput(conv.title);
                        showToast({ message: localize('com_ui_rename_failed') || '重命名失败', status: 'error' });
                    },
                }
            );
        },
        [conv, titleInput, updateConvoMutation, showToast, localize, onRenameSuccess]
    );

    const handleKeyDown = useCallback(
        (e: KeyboardEvent<HTMLInputElement>) => {
            if (e.key === 'Escape') {
                setTitleInput(conv.title);
                setRenaming(false);
            } else if (e.key === 'Enter') {
                submitRename(e);
            }
        },
        [conv.title, submitRename]
    );

    const cancelRename = useCallback(
        (e: MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            e.stopPropagation();
            setTitleInput(conv.title);
            setRenaming(false);
        },
        [conv.title]
    );

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
            setShowDeleteDialog(false);
        },
    });

    const confirmDelete = useCallback(() => {
        const messages = queryClient.getQueryData<TMessage[]>([QueryKeys.messages, conv.id]);
        const thread_id = messages?.[messages.length - 1]?.thread_id;
        const endpoint = messages?.[messages.length - 1]?.endpoint;

        deleteConvoMutation.mutate({ conversationId: conv.id, thread_id, endpoint, source: 'button' });
    }, [conv.id, deleteConvoMutation, queryClient]);

    return (
        <div
            className={cn(
                "group relative w-full content-stretch flex gap-[8px] items-center mb-1 px-[12px] py-[6px] rounded-lg shrink-0 transition-colors cursor-pointer",
                isActive ? "bg-[#e6edfc]" : "fine-pointer:hover:bg-[#f7f7f7] coarse-pointer:hover:bg-transparent",
                renaming ? "bg-[#e6edfc]" : ""
            )}
            onClick={(e) => {
                if (renaming) return;
                // prevent switching if we click dropdown
                if (isPopoverActive || showDeleteDialog) return;
                onClick();
            }}
        >
            {renaming ? (
                <div className="flex h-6 grow cursor-pointer items-center gap-[8px] overflow-hidden whitespace-nowrap break-all">
                    <input
                        ref={inputRef}
                        type="text"
                        className="w-full rounded bg-white px-1 text-[14px] leading-tight focus-visible:outline-none text-[#212121]"
                        value={titleInput ?? ''}
                        onChange={(e) => setTitleInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        onClick={(e) => e.stopPropagation()}
                    />
                    <div className="flex gap-1 shrink-0">
                        <button onClick={cancelRename}>
                            <X className="h-4 w-4 text-[#4e5969] transition-colors duration-200 ease-in-out fine-pointer:hover:opacity-70" />
                        </button>
                        <button onClick={submitRename}>
                            <Check className="h-4 w-4 text-[#165dff] transition-colors duration-200 ease-in-out fine-pointer:hover:opacity-70" />
                        </button>
                    </div>
                </div>
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
                    <span className="text-[#212121] text-[14px] leading-[20px] font-['PingFang_SC:Regular',sans-serif] truncate">
                        {conv.title}
                    </span>
                </div>
            )}

            {/* Dropdown Options */}
            <div
                className={cn(
                    isPopoverActive || isActive
                        ? "flex"
                        : "hidden group-focus-within:flex group-hover:flex",
                    "shrink-0 coarse-pointer:flex",
                )}
                onClick={(e) => e.stopPropagation()}
            >
                {!renaming && (
                    <>
                        <DropdownMenu open={isPopoverActive} onOpenChange={setIsPopoverActive}>
                            <DropdownMenuTrigger asChild>
                                <button
                                    ref={deleteButtonRef}
                                    type="button"
                                    className={cn(
                                        'z-10 flex size-7 shrink-0 items-center justify-center rounded-md text-[#4e5969] outline-none transition-colors hover:bg-black/5',
                                        isActive || isPopoverActive
                                            ? 'opacity-100'
                                            : 'opacity-0 focus:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 coarse-pointer:opacity-100',
                                    )}
                                    onClick={(e) => e.stopPropagation()}
                                    aria-label={localize('com_ui_more')}
                                >
                                    <Outlined.More className="size-4" />
                                </button>
                            </DropdownMenuTrigger>
                            <SidebarListMoreMenuContent onClick={(e) => e.stopPropagation()}>
                                <DropdownMenuItem
                                    className={sidebarListMoreMenuItemClassName}
                                    onClick={handleRenameStart}
                                >
                                    <Outlined.Edit className={sidebarListMoreMenuIconClassName} />
                                    <span className={sidebarListMoreMenuLabelClassName}>
                                        {localize('com_ui_rename')}
                                    </span>
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                    className={sidebarListMoreMenuDangerItemClassName}
                                    onSelect={(e) => {
                                        e.preventDefault();
                                        setIsPopoverActive(false);
                                        setShowDeleteDialog(true);
                                    }}
                                >
                                    <Outlined.Delete className={sidebarListMoreMenuDangerIconClassName} />
                                    <span className={sidebarListMoreMenuDangerLabelClassName}>
                                        {localize('com_ui_delete')}
                                    </span>
                                </DropdownMenuItem>
                            </SidebarListMoreMenuContent>
                        </DropdownMenu>

                        {/* Delete Confirmation Dialog */}
                        {showDeleteDialog && (
                            <OGDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog} triggerRef={deleteButtonRef}>
                                <OGDialogTemplate
                                    showCloseButton={false}
                                    title={localize('com_ui_delete_conversation')}
                                    className="max-w-[450px]"
                                    main={
                                        <div className="flex w-full flex-col items-center gap-2">
                                            <div className="grid w-full items-center gap-2">
                                                <Label className="text-left text-sm font-medium">
                                                    {localize('com_ui_delete_confirm')} <strong>{conv.title}</strong>
                                                </Label>
                                            </div>
                                        </div>
                                    }
                                    selection={{
                                        selectHandler: confirmDelete,
                                        selectClasses: 'bg-red-700 dark:bg-red-600 hover:bg-red-800 dark:hover:bg-red-800 text-white',
                                        selectText: localize('com_ui_delete'),
                                    }}
                                />
                            </OGDialog>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
