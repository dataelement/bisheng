/**
 * TaskTurnLoadContext — lets a TaskTurnPanel report that its history lazy-load
 * failed or is being retried.
 *
 * Why this exists: on a cold load (share page, full refresh) the workspace panel
 * in ChatView builds its file list from the linsight store, which only the task
 * turn's lazy-load fills. When that load fails nothing reaches the store, so the
 * panel cannot tell "load failed" from "no deliverables" on its own. ChatView
 * provides this callback and keeps the failed version ids in local state.
 *
 * Default = no-op so an unwrapped render behaves as before.
 */
import { createContext, useContext } from 'react';

export type ReportTaskTurnLoadFailed = (versionId: string, failed: boolean) => void;

export const TaskTurnLoadContext = createContext<ReportTaskTurnLoadFailed>(() => undefined);

/** Callback for reporting this turn's lazy-load failure to the hosting view. */
export const useReportTaskTurnLoadFailed = (): ReportTaskTurnLoadFailed => useContext(TaskTurnLoadContext);
