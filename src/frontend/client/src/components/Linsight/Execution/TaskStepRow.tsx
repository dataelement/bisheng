/**
 * Task-mode execution — a task's steps rendered INLINE into the single execution
 * timeline (render-optimization Direction A).
 *
 * Why no per-task "row": the plan/checklist already lives in the pinned TaskPanel
 * (the single home of "what was planned / progress"). Rendering each task as its
 * own collapsible row here produced empty, inconsistently-expandable todo rows
 * (a task only had steps if the main agent happened to work under its task_id;
 * the parallel-research todos were fulfilled by subagents whose work is attributed
 * to the session-global bucket, so those todo rows were empty) — visually
 * disconnected from the subagents that actually did the work.
 *
 * So a task now contributes ONLY its real execution to the flow: its sub-steps
 * stream inline via ExecutionTimeline (deep-thinking groups / subagent team /
 * tool rows), plus any answered clarify (IntentRow), nested started children, and
 * a terminal error. A task with no real execution renders nothing.
 */
import { ExecutionLiveContext } from './executionLive';
import { ExecutionTimeline } from './ExecutionTimeline';
import type { ExecStepEventData } from './stepUtils';
import { isTaskRunning, isTaskStarted, TASK_ERROR_STATUSES } from './stepUtils';

export interface ExecTask {
    id: string;
    name: string;
    status: string;
    history?: ExecStepEventData[];
    errorMsg?: string;
    children?: ExecTask[];
    [key: string]: any;
}

export function TaskStepRow({ task }: { task: ExecTask }) {
    // Answered clarify entries render as inline IntentRows inside ExecutionTimeline
    // (时序内联); kept here only to gate the "render nothing" guard below so a task
    // whose only history is an answered clarify still surfaces that intent row.
    const answeredInputs = (task.history || []).filter((h) => h?.step_type === 'call_user_input' && h?.is_completed);
    // Legacy two-level tasks: nested children that execution has actually reached.
    const startedChildren = (task.children || []).filter((child) => isTaskStarted(child.status));
    const hasError = !!task.errorMsg && TASK_ERROR_STATUSES.includes(task.status);
    // Real (non-clarify) execution steps under this task's own id.
    const hasSteps = (task.history || []).some((h) => h?.step_type !== 'call_user_input');
    // Parked on a task-level clarify: an unanswered call_user_input under this
    // task. waiting_for_user_input is in TASK_RUNNING_STATUSES (so isTaskRunning
    // is true), but a parked agent is suspended on an interrupt — nothing is
    // executing — so it must NOT keep the tail episode's clock ticking.
    const awaitingInput = (task.history || []).some(
        (h) => h?.step_type === 'call_user_input' && !h?.is_completed,
    );

    // Direction A: a task with no real execution adds nothing to the timeline —
    // the plan/progress is shown in the pinned TaskPanel, not as an empty flow row.
    if (!hasSteps && !answeredInputs.length && !startedChildren.length && !hasError) return null;

    return (
        <div className="flex flex-col">
            {/* Scope liveness to THIS task: only a running task's tail episode is
                "active" (expanded). A completed task — even though the session is
                still live — passes false so its last episode collapses to a summary
                instead of staying stuck open. */}
            <ExecutionLiveContext.Provider value={isTaskRunning(task.status) && !awaitingInput}>
                <ExecutionTimeline history={task.history} />
            </ExecutionLiveContext.Provider>
            {startedChildren.map((child) => (
                <TaskStepRow key={child.id} task={child} />
            ))}
            {hasError && <p className="px-2 py-1 text-xs text-red-500">{task.errorMsg}</p>}
        </div>
    );
}
