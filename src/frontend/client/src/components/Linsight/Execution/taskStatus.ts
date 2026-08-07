/**
 * Task-status predicates and the session pseudo-task split. Split out of stepUtils.ts.
 */
import type { ExecStepEventData } from './execTypes';
import { buildTimelineGroups } from './stepTree';

// ── shared status helpers ────────────────────────────────────────────────────

export const TASK_DONE_STATUSES = ['success'];
export const TASK_RUNNING_STATUSES = ['in_progress', 'user_input', 'user_input_completed', 'waiting_for_user_input'];
export const TASK_ERROR_STATUSES = ['failed', 'terminated'];

export function isTaskDone(status?: string): boolean {
    return TASK_DONE_STATUSES.includes(status || '');
}

export function isTaskRunning(status?: string): boolean {
    return TASK_RUNNING_STATUSES.includes(status || '');
}

/**
 * A task is "started" once execution has actually reached it — running, finished,
 * or errored. Not-yet-reached tasks (e.g. `not_started`) must NOT appear in the
 * conversation step flow; they only show up in the TaskPanel checklist. The flow
 * reveals steps progressively as they are reached.
 */
export function isTaskStarted(status?: string): boolean {
    return isTaskRunning(status) || isTaskDone(status) || TASK_ERROR_STATUSES.includes(status || '');
}

/**
 * F035 (live vs refresh parity): the backend persists all session-level steps
 * (planning / thinking / write_todos / ask_user) inside a single "执行准备"
 * pseudo-task (``task_data.is_session_global``) so they survive a refresh — see
 * task_exec._ensure_session_pseudo_task. The LIVE flow instead keeps them in a
 * separate inline ``sessionSteps`` bucket; either way the answered clarify renders
 * as an "已经明确用户意图" IntentRow inlined at its chronological position by
 * buildTimelineGroups (时序内联 2026-06) — no longer hoisted to the panel top.
 *
 * To make the reloaded view match the live one, lift the pseudo-task's steps
 * back out: drop it from the rendered task list and expose its ``history`` as
 * the session steps (so they render inline + the clarify becomes an IntentRow).
 * Live steps win when present (active turn); the persisted history is used only
 * on reload. A no-op for sessions without the pseudo-task.
 */
export function splitSessionPseudoTask<T extends { task_data?: any; history?: ExecStepEventData[] }>(
    rawTasks: T[],
    liveSessionSteps: ExecStepEventData[],
): { tasks: T[]; sessionSteps: ExecStepEventData[] } {
    const pseudo = rawTasks.find((t) => t?.task_data?.is_session_global);
    if (!pseudo) return { tasks: rawTasks, sessionSteps: liveSessionSteps };
    return {
        tasks: rawTasks.filter((t) => t !== pseudo),
        sessionSteps: liveSessionSteps.length ? liveSessionSteps : pseudo.history || [],
    };
}
