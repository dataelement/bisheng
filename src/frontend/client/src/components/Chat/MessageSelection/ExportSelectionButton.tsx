/**
 * F028 — The "↓" download icon that enters / exits message selection mode.
 *
 * Visual: a 6×6 button styled to match other action-row icons (Copy, TTS).
 * Clicking on an answer:
 *  - first click enters selection mode for the chat, pre-selecting the pair
 *    group (answer + its query, plus any regenerate siblings) — pair-group
 *    resolution comes from ``useMessageSelection.enterSelectionMode``.
 *  - second click anywhere exits selection mode (button highlights when
 *    active and the title flips to "退出选择" for the user).
 *
 * Used by both surfaces:
 *  - workstation chat (AiMessageBubble's AssistantBubble action row)
 *  - app chat (MessageBs children slot under MessageButtons)
 *
 * Reads ``messages`` from ``useSelectionMessages`` so the parent doesn't
 * have to prop-drill it — the chat list view is expected to wrap its
 * children in ``<SelectionMessagesProvider>``.
 */

import { useCallback } from 'react';
import { Outlined } from 'bisheng-icons';
import { useMessageSelection } from '~/hooks/useMessageSelection';
import { useSelectionMessages } from './SelectionMessagesContext';
import { cn } from '~/utils';

export interface ExportSelectionButtonProps {
    chatId: string;
    messageId: string;
    /** Optional extra classes if a surface needs custom padding/positioning. */
    className?: string;
}

export function ExportSelectionButton({
    chatId,
    messageId,
    className,
}: ExportSelectionButtonProps) {
    const { enterSelectionMode, exitSelectionMode, isActiveForChat } =
        useMessageSelection();
    const messages = useSelectionMessages();
    const active = isActiveForChat(chatId);

    const handleClick = useCallback(
        (event: React.MouseEvent<HTMLButtonElement>) => {
            event.preventDefault();
            event.stopPropagation();
            if (active) {
                exitSelectionMode();
            } else {
                enterSelectionMode(chatId, messageId, messages);
            }
        },
        [active, chatId, messageId, messages, enterSelectionMode, exitSelectionMode],
    );

    return (
        <button
            type="button"
            onClick={handleClick}
            className={cn(
                'flex size-6 items-center justify-center rounded-[6px] backdrop-blur-[4px] transition-colors hover:bg-[#F7F7F7]',
                active && 'bg-[#F0F0F0]',
                className,
            )}
            title={active ? '退出选择' : '导出'}
            aria-label={active ? '退出选择' : '导出'}
            aria-pressed={active}
        >
            <Outlined.FileExport
                size={14}
                className={cn(active ? 'text-[#1677ff]' : 'text-[#818181]')}
            />
        </button>
    );
}
