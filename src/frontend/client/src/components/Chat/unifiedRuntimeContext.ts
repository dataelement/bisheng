/**
 * F004 (T061) — tells the rows of a message list that their page runs on the
 * unified agent runtime (tenant switch `unified_runtime_enabled`, main
 * conversation page only).
 *
 * On such a page a deep-research turn in progress is rendered from the run
 * store, and a stored deep-research turn is shown for review only: no task
 * WebSocket is opened and no question is answered through the legacy
 * user-input API. Default = false, so every other carrier of the bubbles
 * (share page, knowledge docks, `/linsight/:id`) behaves as before.
 */
import { createContext, useContext } from 'react';

export const UnifiedRuntimeContext = createContext(false);

export const useUnifiedRuntimePage = (): boolean => useContext(UnifiedRuntimeContext);

/**
 * Retry of a failed deep-research turn on such a page: sends the turn's
 * question again as a new deep-research message through the page's send entry.
 * Resolves with `false` when the message was not sent.
 */
export type RetryTaskTurn = (question: string) => Promise<boolean | void>;

/** Null (the default) on every carrier that cannot send: no retry is offered there. */
export const TaskTurnRetryContext = createContext<RetryTaskTurn | null>(null);

export const useTaskTurnRetry = (): RetryTaskTurn | null => useContext(TaskTurnRetryContext);
