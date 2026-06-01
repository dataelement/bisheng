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
import { Checkbox } from '~/components/ui/Checkbox';

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
        <Checkbox
            checked={checked}
            // Don't bubble into the message bubble's own click handlers
            // (regenerate, copy, etc.) — selection is the dominant intent
            // while selection mode is active.
            onClick={(event) => event.stopPropagation()}
            onCheckedChange={() => toggleMessage(messageId, messages)}
            className={className}
        />
    );
}
