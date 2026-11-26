/**
 * F035: the task checklist pinned directly above the input box (Figma
 * 12221-39902 expanded / 12221-40080 collapsed). Unlike the in-stream bubble,
 * this stays put above the input for the conversation's latest task turn — both
 * while it runs and after it completes.
 *
 * Two sources, never mixed (F004 design 决策 11):
 *   - The plan of the conversation's current run in `runStore`, keyed by
 *     `conversationId`. The store is filled by the run-events subscription,
 *     which replays the current run on mount, so the plan is back after a
 *     refresh for as long as the server keeps the run's events.
 *   - The stored task list of the latest task turn in the linsight Recoil
 *     store, keyed by `versionId` and hydrated by the in-stream TaskTurnPanel.
 *     Used when `runStore` holds no plan: the run's events expired, or the
 *     turn was stored before runs had a plan.
 */
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { SopStatus } from '~/store/linsight';
import { selectRun, useRunStore, type RunPlanItem, type RunStatus } from '~/store/runStore';
import { PLAN_ROW_CANCELLED, TaskPanel } from './TaskPanel';
import type { ExecTask } from './TaskStepRow';

interface PinnedTaskPanelProps {
    /** Latest task turn of the conversation (stored source). Empty when there is none. */
    versionId?: string;
    /** Conversation shown on the page (run source). */
    conversationId?: string;
}

/**
 * Map the plan of a run to the rows TaskPanel renders. Pure.
 * A row is "in progress" only while the run is active: after a stop or a
 * failure nothing is executing, so no row may keep spinning.
 */
export function planItemsToTasks(items: RunPlanItem[], runStatus: RunStatus): ExecTask[] {
    const active = runStatus === 'running' || runStatus === 'waiting';
    return items.map((item, index) => {
        let status = 'not_started';
        if (item.status === 'completed') status = 'success';
        else if (item.status === 'cancelled') status = PLAN_ROW_CANCELLED;
        else if (item.status === 'in_progress' && active) status = 'in_progress';
        return {
            id: item.id || `row-${index}`,
            name: item.content,
            status,
            previousName: item.previous_content || '',
        };
    });
}

export function PinnedTaskPanel({ versionId = '', conversationId = '' }: PinnedTaskPanelProps) {
    const run = useRunStore(selectRun(conversationId));

    if (run && run.plan.length > 0) {
        const stopped = run.status === 'stopped';
        return (
            <div className="pb-3">
                {/* Key by conversation, not by run: a steer or a follow-up run must
                    not collapse a panel the user has opened. */}
                <TaskPanel
                    key={conversationId}
                    tasks={planItemsToTasks(run.plan, run.status)}
                    completed={run.status === 'finished'}
                    terminated={stopped || run.status === 'failed'}
                    stopped={stopped}
                    awaitingAnswer={run.status === 'waiting' && !!run.pendingQuestion}
                    running={run.status === 'running' || run.status === 'waiting'}
                />
            </div>
        );
    }
    if (!versionId) return null;
    return <StoredPinnedTaskPanel versionId={versionId} />;
}

function StoredPinnedTaskPanel({ versionId }: { versionId: string }) {
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
    // manual stop: the panel should stop spinning and flag a problem instead
    const terminated = status === SopStatus.Stoped;
    // still executing: lets the panel tell "checklist done" apart from "run over"
    const running = status === SopStatus.Running;

    // The card aligns flush with the input box width (no horizontal inset) and
    // keeps a gap below it. Spacing lives here (not in the reusable TaskPanel)
    // so the empty/no-task state leaves no gap above the input.
    return (
        <div className="pb-3">
            {/* Key by versionId so the panel remounts (and its collapsed default
                re-applies) on every conversation switch, instead of carrying the
                previous turn's open/closed state over. */}
            <TaskPanel
                key={versionId}
                tasks={tasks}
                completed={completed}
                terminated={terminated}
                running={running}
            />
        </div>
    );
}
