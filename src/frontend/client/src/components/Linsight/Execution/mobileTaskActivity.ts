import type { BreathingState } from './BreathingRow';
import type { ExecStepEventData } from './execTypes';
import type { ExecTask } from './TaskStepRow';
import { isTaskDone } from './taskStatus';

/** Read only the latest frame metadata; never aggregate or format tool bodies. */
export function getMobileTaskActivity(sessionSteps: ExecStepEventData[], tasks: ExecTask[]): BreathingState {
    if (tasks.length && tasks.every((task) => isTaskDone(task.status))) return 'summarizing';
    const tails: ExecStepEventData[] = sessionSteps.length ? [sessionSteps[sessionSteps.length - 1]] : [];
    const visit = (items: ExecTask[]) => {
        for (const task of items) {
            const history = task.history || [];
            if (history.length) tails.push(history[history.length - 1]);
            if (task.children?.length) visit(task.children);
        }
    };
    visit(tasks);
    const latest = tails.reduce<ExecStepEventData | undefined>((current, frame) =>
        !current || (frame.timestamp ?? 0) >= (current.timestamp ?? 0) ? frame : current, undefined);
    if (!latest || latest.status === 'end') return 'researching';
    const name = (latest.name || '').toLowerCase();
    if (/web_search|websearch/.test(name)) return 'searching';
    if (/read_file|search_knowledge/.test(name)) return 'reading';
    if (/write_file|edit_file/.test(name)) return 'writing';
    return 'researching';
}
