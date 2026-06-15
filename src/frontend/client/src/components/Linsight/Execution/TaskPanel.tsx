/**
 * F035 Track H (P3): task checklist panel (spec §4) — pinned right above the
 * input area. Header: `≣ 任务 N/M  ⌄⌄`; expanded: per-task status list.
 * Status icons: done = gray CheckCircle / running = blue spinning Loading /
 * not-started = gray hollow Circle. Styled to the design mockup.
 */
import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import type { ExecTask } from './TaskStepRow';
import { isTaskDone, isTaskRunning } from './stepUtils';

export function TaskPanel({ tasks, completed }: { tasks: ExecTask[]; completed: boolean }) {
    const localize = useLocalize();
    const [open, setOpen] = useState(false);

    if (!tasks.length) return null;

    const doneCount = tasks.filter((t) => isTaskDone(t.status)).length;
    const allDone = completed || doneCount === tasks.length;

    return (
        <div className="mb-2 w-full rounded-xl border border-gray-200 bg-white shadow-sm">
            {/* header */}
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="flex w-full items-center gap-2 px-4 py-3 text-left"
            >
                <Outlined.ListSuccess size={16} className="shrink-0 text-[#212121]" />
                <span className="shrink-0 text-[16px] font-medium text-[#212121]">
                    {allDone ? localize('com_linsight_task_panel_done') : localize('com_linsight_task_panel')}
                </span>
                <span className="shrink-0 text-[14px] text-[#999]">
                    {doneCount}/{tasks.length}
                </span>
                <span className="ml-auto shrink-0 text-[#999]">
                    {open ? <Outlined.DoubleDown size={16} /> : <Outlined.DoubleUp size={16} />}
                </span>
            </button>

            {/* expanded list */}
            {open && (
                <ul className="max-h-60 overflow-y-auto px-4 pb-2">
                    {tasks.map((task) => {
                        const done = isTaskDone(task.status);
                        const running = isTaskRunning(task.status);
                        return (
                            <li key={task.id} className="flex items-center gap-2.5 py-2 text-[14px]">
                                <span className="flex size-4 shrink-0 items-center justify-center">
                                    {done ? (
                                        <Outlined.CheckCircle size={16} className="text-gray-300" />
                                    ) : running ? (
                                        <Outlined.Loading size={16} className="animate-spin text-primary" />
                                    ) : (
                                        <Outlined.Round size={16} className="text-gray-300" />
                                    )}
                                </span>
                                <span
                                    className={cn(
                                        'min-w-0 flex-1 truncate',
                                        done
                                            ? 'text-[#999]'
                                            : running
                                                ? 'font-medium text-[#212121]'
                                                : 'text-[#212121]',
                                    )}
                                >
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
