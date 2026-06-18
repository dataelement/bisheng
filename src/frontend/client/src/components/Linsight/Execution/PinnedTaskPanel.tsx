/**
 * F035: the task checklist pinned directly above the input box (Figma
 * 12221-39902 expanded / 12221-40080 collapsed). Unlike the in-stream bubble,
 * this stays put above the input for the conversation's latest task turn — both
 * while it runs and after it completes.
 *
 * It only reads from the linsight store; hydration is owned by the in-stream
 * TaskTurnPanel (live WS pump for the active turn, lazy-load for history), so
 * this component re-renders reactively as that store entry fills in.
 */
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { SopStatus } from '~/store/linsight';
import { TaskPanel } from './TaskPanel';
import type { ExecTask } from './TaskStepRow';

export function PinnedTaskPanel({ versionId }: { versionId: string }) {
    const { getLinsight } = useLinsightManager();
    const linsight = getLinsight(versionId);

    // Exclude the "执行准备" session pseudo-task (task_data.is_session_global) —
    // it's a persistence container for session-level steps, not a real checklist
    // item (see splitSessionPseudoTask).
    const tasks: ExecTask[] = ((linsight?.tasks as any) || []).filter(
        (t: any) => !t?.task_data?.is_session_global,
    );
    if (!tasks.length) return null;

    const status = linsight?.status;
    const completed = status === SopStatus.completed || status === SopStatus.FeedbackCompleted;

    // The card aligns flush with the input box width (no horizontal inset) and
    // keeps a gap below it. Spacing lives here (not in the reusable TaskPanel)
    // so the empty/no-task state leaves no gap above the input.
    return (
        <div className="pb-3">
            <TaskPanel tasks={tasks} completed={completed} />
        </div>
    );
}
