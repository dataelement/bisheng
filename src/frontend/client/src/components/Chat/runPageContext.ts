/**
 * F004 (T061) — tells the rows of a message list that their page follows the
 * run events of its conversation (the main conversation page, not its share
 * view).
 *
 * On such a page a deep-research turn in progress is rendered from the run
 * store, and a stored deep-research turn is shown for review only: no task
 * WebSocket is opened and no question is answered through the legacy
 * user-input API. Default = false: the other carriers of the bubbles (share
 * page, knowledge docks) follow no run events.
 */
import { createContext, useContext } from 'react';

export const RunPageContext = createContext(false);

export const useRunPage = (): boolean => useContext(RunPageContext);

/**
 * Retry of a failed deep-research turn on such a page: sends the turn's
 * question again as a new deep-research message through the page's send entry.
 * Resolves with `false` when the message was not sent.
 */
export type RetryTaskTurn = (question: string) => Promise<boolean | void>;

/** Null (the default) on every carrier that cannot send: no retry is offered there. */
export const TaskTurnRetryContext = createContext<RetryTaskTurn | null>(null);

export const useTaskTurnRetry = (): RetryTaskTurn | null => useContext(TaskTurnRetryContext);
