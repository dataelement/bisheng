/**
 * F035 Track H (P3): top-level task row (spec §3) — check/spinner/title;
 * expanded: the sub-step flow of that task (tool/knowledge/thinking/subagent/
 * ui_card rows, grouped by the event's task_id) plus answered clarify rows.
 */
import { Check, Circle, XCircle } from 'lucide-react';
import { cn } from '~/utils';
import { RunningSpinner, StepRow } from './StepRow';
import { StepList } from './StepList';
import { IntentRow } from './IntentRow';
import type { ExecStepEventData } from './stepUtils';
import { isTaskDone, isTaskRunning, TASK_ERROR_STATUSES } from './stepUtils';

export interface ExecTask {
    id: string;
    name: string;
    status: string;
    history?: ExecStepEventData[];
    errorMsg?: string;
    children?: ExecTask[];
    [key: string]: any;
}

function statusIcon(status: string) {
    if (isTaskDone(status)) return <Check size={14} className="text-gray-400" />;
    if (isTaskRunning(status)) return <RunningSpinner />;
    if (TASK_ERROR_STATUSES.includes(status)) return <XCircle size={14} className="text-red-400" />;
    return <Circle size={10} className="text-gray-300" />;
}

export function TaskStepRow({ task }: { task: ExecTask }) {
    const running = isTaskRunning(task.status);
    const done = isTaskDone(task.status);
    // answered clarify entries collapse into intent-summary rows inside the task
    const answeredInputs = (task.history || []).filter(
        (h) => h?.step_type === 'call_user_input' && h?.is_completed,
    );
    const hasContent =
        (task.history || []).some((h) => h?.step_type !== 'call_user_input') ||
        answeredInputs.length > 0 ||
        (task.children || []).length > 0;

    return (
        <StepRow
            icon={statusIcon(task.status)}
            title={task.name}
            running={running}
            titleClassName={cn(done && 'text-gray-400')}
        >
            {hasContent ? (
                <div className="flex flex-col">
                    {answeredInputs.map((entry, i) => (
                        <IntentRow key={`input_${i}`} data={entry} />
                    ))}
                    <StepList history={task.history} />
                    {/* legacy two-level tasks: render children as nested task rows */}
                    {(task.children || []).map((child) => (
                        <TaskStepRow key={child.id} task={child} />
                    ))}
                    {task.errorMsg && TASK_ERROR_STATUSES.includes(task.status) && (
                        <p className="px-2 py-1 text-xs text-red-500">{task.errorMsg}</p>
                    )}
                </div>
            ) : undefined}
        </StepRow>
    );
}
