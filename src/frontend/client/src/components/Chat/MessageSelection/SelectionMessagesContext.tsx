/**
 * F028 — React Context that ferries the *current* messages list from the
 * chat list view (AiChatMessages and friends) down to descendants that need
 * it for pair-group resolution (MessageCheckbox + ExportSelectionButton).
 *
 * Why a context rather than a react-query cache lookup: the workstation
 * chat hook (``useAiChat``) keeps messages in component state, not in
 * react-query. Reaching for ``QueryKeys.messages`` returns ``undefined``
 * here. A context that the list view fills on every render keeps the
 * cascading-selection logic correct without modifying ``useAiChat``.
 *
 * Why not pass via prop drilling: AiMessageBubble is two levels removed
 * from the list scope, and there are multiple call sites (flat mode +
 * tree mode + workflow chat). Context is the lighter touch.
 */

import { createContext, useContext, type ReactNode } from 'react';
import type { SelectableMessage } from '~/hooks/useMessageSelection';

const SelectionMessagesContext = createContext<readonly SelectableMessage[]>([]);

export interface SelectionMessagesProviderProps {
    messages: readonly SelectableMessage[];
    children: ReactNode;
}

export function SelectionMessagesProvider({
    messages,
    children,
}: SelectionMessagesProviderProps) {
    return (
        <SelectionMessagesContext.Provider value={messages}>
            {children}
        </SelectionMessagesContext.Provider>
    );
}

/**
 * Read the current messages list from the nearest SelectionMessagesProvider.
 * Falls back to an empty array when no provider is mounted — this keeps the
 * checkbox / export button safe in legacy chat surfaces that haven't been
 * wired yet (returns an empty pair-group, which is a graceful degradation).
 */
export function useSelectionMessages(): readonly SelectableMessage[] {
    return useContext(SelectionMessagesContext);
}
