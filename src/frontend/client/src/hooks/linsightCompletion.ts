import type { ExecTask } from '~/components/Linsight/Execution/TaskStepRow';

const TERMINAL_TASK_STATUSES = new Set(['success', 'failed', 'terminated']);

/** Mirror the backend's completion sweep; never mark unfinished work successful. */
export function closeCompletedTaskRows(tasks: ExecTask[]): ExecTask[] {
    return tasks.map((task) => ({
        ...task,
        status: TERMINAL_TASK_STATUSES.has(task.status) ? task.status : 'terminated',
        children: closeCompletedTaskRows(task.children || []),
    }));
}
