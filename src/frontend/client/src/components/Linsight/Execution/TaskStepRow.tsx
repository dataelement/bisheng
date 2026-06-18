/**
 * F035 Track H (P3): top-level task row (spec §3) — check/spinner/title;
 * expanded: the sub-step flow of that task (tool/knowledge/thinking/subagent/
 * ui_card rows, grouped by the event's task_id) plus answered clarify rows.
 */
import { Circle, XCircle } from 'lucide-react';
import { useMemo } from 'react';
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { RunningSpinner, StepRow } from './StepRow';
import { ExecutionTimeline } from './ExecutionTimeline';
import { IntentRow } from './IntentRow';
import type { ExecStepEventData, FlowNode, SubagentGroup } from './stepUtils';
import { activeFlowNode, firstLine, isTaskDone, isTaskRunning, isTaskStarted, TASK_ERROR_STATUSES } from './stepUtils';

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

/** Elapsed seconds spanned by a subagent team group (across all agents + their
 *  child steps), from the earliest startedAt to the latest endedAt. 0 when no
 *  timestamps are available. */
function groupElapsedSeconds(group: SubagentGroup): number {
    let min = Infinity;
    let max = -Infinity;
    group.agents.forEach((agent) => {
        [agent.step, ...agent.children].forEach((s) => {
            if (s.startedAt !== undefined) min = Math.min(min, s.startedAt);
            if (s.endedAt !== undefined) max = Math.max(max, s.endedAt);
        });
    });
    if (min === Infinity || max === -Infinity || max < min) return 0;
    return max - min;
}

export function TaskStepRow({ task }: { task: ExecTask }) {
    const localize = useLocalize();
    const running = isTaskRunning(task.status);
    const done = isTaskDone(task.status);

    // Collapsed + running: the header summarizes the currently-running sub-step
    // (mirrors the label its expanded row renders); expanded shows the task name.
    const flowNodeLabel = (node: FlowNode): string => {
        if (node.kind === 'subagent_group') {
            // Team-running / done summary: {{0}} = number of distinct subagents
            // (one per subgraph namespace), {{1}} = elapsed seconds of the group.
            const teamRunning = node.agents.some((a) => a.step.running);
            return localize(teamRunning ? 'com_linsight_subagent_team_running' : 'com_linsight_subagent_team_done', {
                0: String(node.agents.length),
                1: String(groupElapsedSeconds(node)),
            });
        }
        // thinking: prefer a one-line fingerprint of the streamed output, falling
        // back to the generic "Thinking" label when the output is still empty.
        if (node.step.stepType === 'thinking') {
            return firstLine(node.step.output) || localize('com_linsight_thinking');
        }
        return node.step.name;
    };
    const taskName = task.name || task.task_data?.name;
    // F3 perf: activeFlowNode rebuilds the node tree (merge + group) every render.
    // Same in-place WS mutation caveat as ExecutionTimeline — key the memo on a
    // composite signature of the history (length + last frame status / call_id).
    const history = task.history || [];
    const lastFrame = history[history.length - 1];
    const historySig = `${history.length}:${lastFrame?.status ?? ''}:${lastFrame?.call_id ?? ''}`;
    const runningNode = useMemo(
        () => (running ? activeFlowNode(task.history) : null),
        [running, historySig], // eslint-disable-line react-hooks/exhaustive-deps
    );
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
                    <ExecutionTimeline history={task.history} />
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
