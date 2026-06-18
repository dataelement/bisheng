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
    // Default expanded (user decision, Wave2): the checklist opens by default so
    // the per-task progress is visible without an extra click; position unchanged
    // (still pinned above the input).
    const [open, setOpen] = useState(true);

    if (!tasks.length) return null;

    const doneCount = tasks.filter((t) => isTaskDone(t.status)).length;
    const allDone = completed || doneCount === tasks.length;

    // Collapsed header surfaces the currently-running task name inline (Figma
    // 12221-40080): `≣ 任务  <running task>  N/M  ⌃`. While expanded the list
    // below already shows every task, so the header omits the inline name.
    const runningTask = tasks.find((t) => isTaskRunning(t.status));
    const runningName = runningTask?.name || runningTask?.task_data?.name || '';
    const showRunningInline = !open && !allDone && !!runningName;

    return (
        <div className="w-full rounded-xl border border-[#ECECEC] bg-white">
            {/* header */}
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="flex w-full items-center gap-2 px-4 py-3 text-left"
            >
                {runningTask ? (
                    <Outlined.Loading size={16} className="shrink-0 animate-spin text-primary" />
                ) : (
                    <Outlined.ListSuccess size={16} className="shrink-0 text-[#212121]" />
                )}
                <span className="shrink-0 text-[16px] font-medium text-[#212121]">
                    {allDone ? localize('com_linsight_task_panel_done') : localize('com_linsight_task_panel')}
                </span>
                {showRunningInline && (
                    <span className="min-w-0 flex-1 truncate bg-[linear-gradient(90deg,#cccccc_0%,#6b6b6b_50%,#cccccc_100%)] bg-[length:200%_100%] bg-clip-text text-[14px] text-transparent animate-text-shimmer">
                        {runningName}
                    </span>
                )}
                <span className={cn('shrink-0 text-[14px] text-[#999]', showRunningInline ? 'ml-2' : 'ml-1')}>
                    {doneCount}/{tasks.length}
                </span>
                <span className={cn('shrink-0 text-[#999]', showRunningInline ? 'ml-2' : 'ml-auto')}>
                    {/* one rotating chevron (down = expanded, up = collapsed) so the
                        glyph eases between states instead of hard-swapping */}
                    <Outlined.DoubleDown
                        size={16}
                        className={cn('transition-transform duration-300 ease-in-out', open ? '' : 'rotate-180')}
                    />
                </span>
            </button>

            {/* expanded list — grid 0fr→1fr animates the height smoothly in both
                directions without measuring; the inner overflow-hidden clips the
                rows mid-transition. */}
            <div
                className={cn(
                    'grid transition-[grid-template-rows] duration-300 ease-in-out',
                    open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]',
                )}
            >
                <div className="overflow-hidden">
                    <ul className="max-h-60 overflow-y-auto px-4 pb-2 scrollbar-os">
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
                </div>
            </div>
        </div>
    );
}
