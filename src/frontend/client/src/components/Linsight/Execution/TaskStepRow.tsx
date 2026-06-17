/**
 * F035 Track H (P3): top-level task row (spec §3) — check/spinner/title;
 * expanded: the sub-step flow of that task (tool/knowledge/thinking/subagent/
 * ui_card rows, grouped by the event's task_id) plus answered clarify rows.
 */
import { Circle, XCircle } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { RunningSpinner, StepRow } from './StepRow';
import { StepList } from './StepList';
import { IntentRow } from './IntentRow';
import type { ExecStepEventData, FlowNode } from './stepUtils';
import { activeFlowNode, isTaskDone, isTaskRunning, isTaskStarted, TASK_ERROR_STATUSES } from './stepUtils';

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
    if (isTaskDone(status)) return <Outlined.DoubleCheck size={16} className="text-[#333]" />;
    if (isTaskRunning(status)) return <RunningSpinner />;
    if (TASK_ERROR_STATUSES.includes(status)) return <XCircle size={16} className="text-red-400" />;
    return <Circle size={16} className="text-[#333]" />;
}

export function TaskStepRow({ task }: { task: ExecTask }) {
    const localize = useLocalize();
    const running = isTaskRunning(task.status);
    const done = isTaskDone(task.status);

    // Collapsed + running: the header summarizes the currently-running sub-step
    // (mirrors the label its expanded row renders); expanded shows the task name.
    const flowNodeLabel = (node: FlowNode): string => {
        if (node.kind === 'subagent_group') {
            const base = localize('com_linsight_subagent_delegate', {
                0: String(node.agents.length),
                1: node.name,
            });
            const reason = node.agents[0]?.step.callReason;
            return reason ? `${base}（${reason}）` : base;
        }
        if (node.step.stepType === 'thinking') return node.step.name || localize('com_linsight_thinking');
        return node.step.name;
    };
    const taskName = task.name || task.task_data?.name;
    const runningNode = running ? activeFlowNode(task.history) : null;
    const runningLabel = (runningNode && flowNodeLabel(runningNode)) || taskName;
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
            // running: collapsed shows a spinner + running sub-step name; expanded
            // shows the task list icon + the task's own name (sub-rows carry their
            // own loading). defaultOpen=false keeps every task node collapsed by default.
            icon={(open) =>
                running && open ? (
                    <Outlined.ListSuccess size={16} className="text-[#333]" />
                ) : (
                    statusIcon(task.status)
                )
            }
            title={(open) => (running && !open ? runningLabel : taskName)}
            running={running}
            defaultOpen={false}
            titleClassName={cn(done && 'text-gray-400')}
        >
            {hasContent ? (
                <div className="flex flex-col">
                    {answeredInputs.map((entry, i) => (
                        <IntentRow key={`input_${i}`} data={entry} />
                    ))}
                    <StepList history={task.history} />
                    {/* legacy two-level tasks: render children as nested task rows —
                        same rule, only show children execution has reached */}
                    {(task.children || []).filter((child) => isTaskStarted(child.status)).map((child) => (
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
