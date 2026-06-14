/**
 * F035 Track H (P3): task checklist panel (spec §4) — pinned right above the
 * input area. Collapsed: one line `≡ 任务 <current task> N/M ⌃`;
 * expanded: full list with ✓ done / spinner in-progress / ○ not-started.
 * Completed run: `任务已完成 <last task> M/M`.
 */
import { AlignLeft, Check, ChevronDown, ChevronUp, Circle } from 'lucide-react';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { RunningSpinner } from './StepRow';
import type { ExecTask } from './TaskStepRow';
import { isTaskDone, isTaskRunning } from './stepUtils';

export function TaskPanel({ tasks, completed }: { tasks: ExecTask[]; completed: boolean }) {
    const localize = useLocalize();
    const [open, setOpen] = useState(false);

    if (!tasks.length) return null;

    const doneCount = tasks.filter((t) => isTaskDone(t.status)).length;
    const current = tasks.find((t) => isTaskRunning(t.status)) || tasks[tasks.length - 1];
    const allDone = completed || doneCount === tasks.length;
    const headTask = allDone ? tasks[tasks.length - 1] : current;

    return (
        <div className="mb-2 w-full rounded-xl border border-gray-200 bg-white shadow-sm">
            {/* collapsed summary line / panel header */}
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="flex w-full items-center gap-2 px-3 py-2 text-sm"
            >
                <AlignLeft size={14} className="shrink-0 text-gray-400" />
                <span className="shrink-0 font-medium text-gray-700">
                    {allDone ? localize('com_linsight_task_panel_done') : localize('com_linsight_task_panel')}
                </span>
                <span className="min-w-0 flex-1 truncate text-left text-gray-500">{headTask?.name || headTask?.task_data?.name}</span>
                <span className="shrink-0 text-xs text-gray-400">
                    {doneCount}/{tasks.length}
                </span>
                <span className="shrink-0 text-gray-400">
                    {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </span>
            </button>

            {/* expanded full list */}
            {open && (
                <ul className="max-h-52 overflow-y-auto border-t border-gray-100 px-3 py-2">
                    {tasks.map((task) => {
                        const done = isTaskDone(task.status);
                        const running = isTaskRunning(task.status);
                        return (
                            <li key={task.id} className="flex items-center gap-2 py-1 text-sm">
                                <span className="flex size-4 shrink-0 items-center justify-center">
                                    {done ? (
                                        <Check size={13} className="text-gray-400" />
                                    ) : running ? (
                                        <RunningSpinner />
                                    ) : (
                                        <Circle size={9} className="text-gray-300" />
                                    )}
                                </span>
                                <span className={cn('min-w-0 flex-1 truncate', done ? 'text-gray-400' : 'text-gray-700')}>
                                    {task.name || task.task_data?.name}
                                </span>
                            </li>
                        );
                    })}
                </ul>
            )}
        </div>
    );
}
