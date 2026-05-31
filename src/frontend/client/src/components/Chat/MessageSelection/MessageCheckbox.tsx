/**
 * F028 — Circular checkbox shown to the left of each message while the
 * conversation export "selection mode" is active.
 *
 * The checkbox reads the visible message list directly from the
 * react-query cache (key: ``[QueryKeys.messages, chatId]``) so call sites
 * only need to pass ``chatId`` and ``messageId``. This keeps MessageRender
 * et al. free of prop drilling.
 *
 * The cascading toggle (the query/answer pair group selects/unselects
 * together) lives in useMessageSelection.
 */

import { useMessageSelection } from '~/hooks/useMessageSelection';
import { useSelectionMessages } from './SelectionMessagesContext';
import { cn } from '~/utils';

interface MessageCheckboxProps {
    /** The chat this message belongs to (currently unused — Context-scoped). */
    chatId: string;
    /** The message this checkbox toggles. */
    messageId: string;
    /** Optional extra classes for layout positioning. */
    className?: string;
}

export function MessageCheckbox({ messageId, className }: MessageCheckboxProps) {
    const { isSelected, toggleMessage } = useMessageSelection();
    const messages = useSelectionMessages();
    const checked = isSelected(messageId, messages);

    return (
        <button
            type="button"
            role="checkbox"
            aria-checked={checked}
            onClick={(e) => {
                // Don't bubble into the message bubble's own click handlers
                // (regenerate, copy, etc.) — selection is the dominant intent
                // while selection mode is active.
                e.stopPropagation();
                toggleMessage(messageId, messages);
            }}
            className={cn(
                'inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors',
                checked
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border bg-background hover:border-primary/60',
                className,
            )}
        >
            {checked && (
                <svg
                    viewBox="0 0 12 12"
                    className="h-3 w-3"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2.5}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                >
                    <polyline points="2.5 6.5 5 9 9.5 3.5" />
                </svg>
            )}
        </button>
    );
}
