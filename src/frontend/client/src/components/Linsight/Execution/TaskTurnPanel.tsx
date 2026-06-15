/**
 * F035 Track J (TJ-7): inline task-turn panel.
 *
 * Renders ONE task turn's execution detail embedded in the daily message
 * stream (not the full-page /linsight view). A task turn is a bot ChatMessage
 * with `category==='task'` + `linsightSessionVersionId`; this panel reuses the
 * leaf execution components (StepList / TaskStepRow / ClarifyCard / ResultSection
 * / TaskPanel) keyed by that SV.
 *
 * Two hydration paths:
 *  - LIVE (just submitted this session): `linsightMapState[svid]` is already
 *    seeded by useAiChat's handoff handler; the WS pump (self-guards on
 *    status===Running) drives it. We just render from the store.
 *  - HISTORY (page refresh / loaded from message history): the store is empty,
 *    so we lazy-load the execution detail by SV (session-version-list + task
 *    list) and seed the store. An in-flight turn (status in_progress) then
 *    reconnects the WS automatically; a completed one stays read-only.
 *
 * The question bubble and follow-up input are intentionally NOT rendered here —
 * the daily message list owns the linear Q→A flow, and a follow-up is just the
 * next daily turn (new SV under decision A). HITL clarify stays on the linsight
 * WS (sendInput).
 */
import { CircleAlert, OctagonX } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { getLinsightSessionVersionList, getLinsightTaskList } from '~/api/linsight';
import { FilePreviewPanel } from '~/components/Linsight/Artifacts/FilePreviewPanel';
import { ResultSection } from '~/components/Linsight/Artifacts/ResultSection';
import { WorkspaceDrawer } from '~/components/Linsight/Artifacts/WorkspaceDrawer';
import { useArtifactsPanel } from '~/components/Linsight/Artifacts/useArtifactsPanel';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { useLocalize } from '~/hooks';
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { useLinsightWebSocket } from '~/hooks/Websocket';
import { SopStatus } from '~/store/linsight';
import { ClarifyCard } from './ClarifyCard';
import { IntentRow } from './IntentRow';
import { PlanningRow } from './PlanningRow';
import { StepList } from './StepList';
import { TaskPanel } from './TaskPanel';
import { TaskStepRow, type ExecTask } from './TaskStepRow';
import type { ExecStepEventData } from './stepUtils';

interface TaskTurnPanelProps {
    /** linsight session_version id holding this turn's execution detail */
    versionId: string;
    /** chat id of the hosting conversation (for the history lazy-load) */
    conversationId?: string;
    /** final answer text (fallback shown before the panel hydrates) */
    answer?: string;
    /** read-only (share page) — disable clarify input */
    readOnly?: boolean;
}

/** Collect every clarify (call_user_input) entry across session + tasks. */
function collectUserInputs(sessionSteps: ExecStepEventData[], tasks: ExecTask[]) {
    const entries: ExecStepEventData[] = [];
    sessionSteps.forEach((s) => s?.step_type === 'call_user_input' && entries.push(s));
    tasks.forEach((task) => {
        (task.history || []).forEach((h) => h?.step_type === 'call_user_input' && entries.push(h));
        (task.children || []).forEach((child) =>
            (child.history || []).forEach((h) => h?.step_type === 'call_user_input' && entries.push(h)),
        );
    });
    return entries;
}

export function TaskTurnPanel({ versionId, conversationId, answer, readOnly = false }: TaskTurnPanelProps) {
    const localize = useLocalize();
    const { getLinsight, switchAndUpdateLinsight } = useLinsightManager();
    const artifactsPanel = useArtifactsPanel();
    // WS pump — self-guards on status===Running, so mounting it for a completed
    // historical turn is a no-op (no connection opened).
    const { sendInput } = useLinsightWebSocket(versionId);

    const linsight = getLinsight(versionId);
    const [loadFailed, setLoadFailed] = useState(false);

    // HISTORY hydration: no store entry yet → lazy-load this SV's detail.
    const loadedRef = useRef(false);
    useEffect(() => {
        if (!versionId || linsight || loadedRef.current) return;
        if (!conversationId || conversationId === 'new') return;
        loadedRef.current = true;
        (async () => {
            try {
                const versions = await getLinsightSessionVersionList(conversationId, '');
                const item = (versions || []).find((v: any) => v.id === versionId);
                if (!item) {
                    setLoadFailed(true);
                    return;
                }
                const tasks = await getLinsightTaskList(versionId, item, '');
                switchAndUpdateLinsight(versionId, { ...item, tasks });
            } catch (e) {
                console.error('[TaskTurnPanel] failed to load task detail:', e);
                setLoadFailed(true);
            }
        })();
    }, [versionId, conversationId, linsight, switchAndUpdateLinsight]);

    const tasks: ExecTask[] = (linsight?.tasks as any) || [];
    const sessionSteps: ExecStepEventData[] = (linsight as any)?.sessionSteps || [];
    const status = linsight?.status;
    console.log("[TJ][Panel] render. svid:", versionId, "hasLinsight:", !!linsight, "status:", status, "tasks:", tasks.length, "sessionSteps:", sessionSteps.length);
    const running = status === SopStatus.Running;
    const completed = status === SopStatus.completed || status === SopStatus.FeedbackCompleted;
    const stopped = status === SopStatus.Stoped;
    const fileList: ArtifactFile[] = (linsight?.file_list as ArtifactFile[]) || [];

    const pendingInput = useMemo(() => {
        if (!running) return null;
        const entries = collectUserInputs(sessionSteps, tasks);
        return [...entries].reverse().find((e) => !e.is_completed) || null;
    }, [running, sessionSteps, tasks]);

    const answeredSessionInputs = useMemo(
        () => sessionSteps.filter((s) => s?.step_type === 'call_user_input' && s?.is_completed),
        [sessionSteps],
    );

    const planning = running && !tasks.length && !pendingInput;

    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => {
        console.log("[TJ][Panel] STATE CHANGED → status:", status, "running:", running,
            "tasks:", tasks.length, "sessionSteps:", sessionSteps.length,
            "pendingInput:", !!pendingInput, "planning:", planning, "completed:", completed);
    }, [status, tasks.length, sessionSteps.length, pendingInput, running, planning, completed]);

    const handleClarifySubmit = (taskId: string, ans: string) => {
        sendInput({ task_id: taskId || versionId, user_input: ans, files: [] });
    };

    // Not hydrated yet — show the answer text fallback (or a thin loading hint).
    if (!linsight) {
        if (loadFailed) {
            return (
                <div className="text-[14px] leading-relaxed text-[#212121]">
                    {answer || localize('com_linsight_detail_load_failed')}
                </div>
            );
        }
        return answer ? (
            <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-[#212121]">{answer}</div>
        ) : (
            <div className="py-2 text-sm text-[#86909c]">{localize('com_linsight_loading')}</div>
        );
    }

    return (
        <div className="w-full">
            {/* answered session-level clarifies -> intent summary rows */}
            {answeredSessionInputs.map((entry, i) => (
                <IntentRow key={`intent_${i}`} data={entry} />
            ))}

            {/* session-level steps (planning-stage tools etc.) */}
            <StepList history={sessionSteps} />

            {/* planning breathing row */}
            {planning && <PlanningRow />}

            {/* task rows with nested sub-step flows */}
            {tasks.map((task) => (
                <TaskStepRow key={task.id} task={task} />
            ))}

            {/* active clarify card (HITL stays on linsight WS) */}
            {pendingInput && (
                <ClarifyCard data={pendingInput} disabled={readOnly} onSubmit={handleClarifySubmit} />
            )}

            {/* error / terminated banners */}
            {linsight.taskError && (
                <div className="my-2 flex items-start gap-2 rounded-xl border border-red-100 bg-red-50/60 p-3 text-sm text-red-600">
                    <CircleAlert size={16} className="mt-0.5 shrink-0" />
                    <span className="whitespace-pre-wrap break-words">{linsight.taskError}</span>
                </div>
            )}
            {stopped && !linsight.taskError && (
                <div className="my-2 flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-500">
                    <OctagonX size={16} className="shrink-0" />
                    {localize('com_linsight_task_terminated')}
                </div>
            )}

            {/* waiting-for-input hint */}
            {pendingInput && (
                <div className="mb-2 mt-2 flex items-center gap-2 rounded-lg bg-blue-50 px-3 py-1.5 text-xs text-blue-600">
                    <span className="size-1.5 animate-pulse rounded-full bg-blue-500" />
                    {localize('com_linsight_waiting_your_input')}
                </div>
            )}

            {/* task checklist progress */}
            <TaskPanel tasks={tasks} completed={completed} />

            {/* artifacts: report link / answer markdown / file card */}
            {completed && (
                <div data-slot="execution-artifacts" className="mt-4">
                    <ResultSection
                        answer={linsight.output_result?.answer}
                        files={fileList}
                        versionId={versionId}
                        onPreview={(file) => artifactsPanel.openPreview(file)}
                    />
                </div>
            )}

            {/* right-side workspace / preview drawers (shared, mutually exclusive) */}
            <WorkspaceDrawer
                open={artifactsPanel.workspaceOpen}
                onOpenChange={artifactsPanel.setWorkspaceOpen}
                files={fileList}
                onPreview={(file) => artifactsPanel.openPreview(file, true)}
            />
            <FilePreviewPanel
                open={!!artifactsPanel.previewFile}
                onOpenChange={(open) => !open && artifactsPanel.closePreview()}
                file={artifactsPanel.previewFile}
                versionId={versionId}
                onBack={artifactsPanel.fromWorkspace ? artifactsPanel.backToWorkspace : undefined}
            />
        </div>
    );
}
