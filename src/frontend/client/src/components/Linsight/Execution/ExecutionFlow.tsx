/**
 * F035 Track H (P3): the new conversational execution view (spec §0/§3) —
 * replaces the legacy SOPEditor/TaskFlow split panes. Top-down flow:
 *   user question bubble → step rows (appended as WS events stream in) →
 *   artifacts area (P4 slot) → footer: task checklist panel + unified input.
 * Everything renders from the Recoil linsight store keyed by versionId; the
 * WS hook (task-message-stream) is mounted here so the event pump stays alive
 * after the old TaskFlow stops rendering.
 */
import { CircleAlert, FolderOpen, OctagonX } from 'lucide-react';
import { useMemo, useRef, type ReactNode } from 'react';
import { SopStatus } from '~/components/Sop/SOPEditor';
import { FilePreviewPanel } from '~/components/Linsight/Artifacts/FilePreviewPanel';
import { ResultSection } from '~/components/Linsight/Artifacts/ResultSection';
import { WorkspaceDrawer } from '~/components/Linsight/Artifacts/WorkspaceDrawer';
import { useArtifactsPanel } from '~/components/Linsight/Artifacts/useArtifactsPanel';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { TaskModeInput } from '~/components/Linsight/Input/TaskModeInput';
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { useLinsightWebSocket } from '~/hooks/Websocket';
import { useAutoScroll } from '~/hooks/useAutoScroll';
import { useLocalize } from '~/hooks';
import { ClarifyCard } from './ClarifyCard';
import { IntentRow } from './IntentRow';
import { PlanningRow } from './PlanningRow';
import { QueueCard } from './QueueCard';
import { StepList } from './StepList';
import { TaskPanel } from './TaskPanel';
import { TaskStepRow, type ExecTask } from './TaskStepRow';
import type { ExecStepEventData } from './stepUtils';

interface ExecutionFlowProps {
    versionId: string;
    /** conversation id for the input's per-session memory */
    conversationId?: string;
    isSharePage?: boolean;
    /** share-page footer (e.g. "make same style"), injected to avoid imports back into Sop */
    shareControls?: ReactNode;
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

export function ExecutionFlow({ versionId, conversationId, isSharePage = false, shareControls }: ExecutionFlowProps) {
    const localize = useLocalize();
    const { getLinsight } = useLinsightManager();
    // Mount the WS pump here (the legacy TaskFlow used to own it).
    const { stop, sendInput } = useLinsightWebSocket(versionId);

    const linsight = getLinsight(versionId);
    const tasks: ExecTask[] = (linsight?.tasks as any) || [];
    const sessionSteps: ExecStepEventData[] = (linsight as any)?.sessionSteps || [];
    const status = linsight?.status;
    const running = status === SopStatus.Running;
    const completed = status === SopStatus.completed || status === SopStatus.FeedbackCompleted;
    const stopped = status === SopStatus.Stoped;
    const queueing = running && (linsight?.queueCount || 0) > 0;

    // P4 artifacts: output files + the shared right-side panel (workspace/preview)
    const fileList: ArtifactFile[] = (linsight?.file_list as ArtifactFile[]) || [];
    const artifactsPanel = useArtifactsPanel();

    // clarify requests: the newest unanswered one is the active card;
    // session-level answered ones become flow-level intent rows
    // (task-level answered ones render inside their TaskStepRow)
    const pendingInput = useMemo(() => {
        if (!running) return null;
        const entries = collectUserInputs(sessionSteps, tasks);
        return [...entries].reverse().find((e) => !e.is_completed) || null;
    }, [running, sessionSteps, tasks]);

    const answeredSessionInputs = useMemo(
        () => sessionSteps.filter((s) => s?.step_type === 'call_user_input' && s?.is_completed),
        [sessionSteps],
    );

    // planning row: running, todo list not generated yet, nothing else pending
    const planning = running && !queueing && !tasks.length && !pendingInput;

    const handleClarifySubmit = (taskId: string, answer: string) => {
        sendInput({ task_id: taskId || versionId, user_input: answer, files: [] });
    };

    const scrollRef = useRef<HTMLDivElement>(null);
    useAutoScroll(scrollRef, [tasks, sessionSteps, status]);

    return (
        <div className="relative flex h-full w-full flex-col">
            {/* workspace entry (spec §5 fig 9: top-right icon, shown once completed) */}
            {completed && fileList.length > 0 && (
                <button
                    type="button"
                    title={localize('com_linsight_workspace')}
                    aria-label={localize('com_linsight_workspace')}
                    className="absolute right-4 top-3 z-10 rounded-lg border border-gray-200 bg-white p-2 text-gray-600 shadow-sm hover:bg-gray-50"
                    onClick={artifactsPanel.openWorkspace}
                >
                    <FolderOpen size={16} />
                </button>
            )}

            {/* ── conversational flow ─────────────────────────────────────── */}
            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto scroll-hover">
                <div className="mx-auto w-full max-w-[800px] px-4 pb-6 pt-4">
                    {/* user question bubble */}
                    {linsight?.question && (
                        <div className="mb-4 flex justify-end">
                            <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-blue-50 px-4 py-2.5 text-sm text-gray-800">
                                {linsight.question}
                            </div>
                        </div>
                    )}

                    {/* queueing card (auto-disappears when the worker picks us up) */}
                    {queueing && <QueueCard position={linsight!.queueCount} onCancel={stop} />}

                    {!queueing && (
                        <>
                            {/* session-level answered clarifies -> intent summary rows */}
                            {answeredSessionInputs.map((entry, i) => (
                                <IntentRow key={`intent_${i}`} data={entry} />
                            ))}

                            {/* session-level steps (task_id == svid pseudo task, e.g. planning-stage tools) */}
                            <StepList history={sessionSteps} />

                            {/* planning breathing row */}
                            {planning && <PlanningRow />}

                            {/* task rows with nested sub-step flows */}
                            {tasks.map((task) => (
                                <TaskStepRow key={task.id} task={task} />
                            ))}

                            {/* active clarify / follow-up card */}
                            {pendingInput && (
                                <ClarifyCard data={pendingInput} disabled={isSharePage} onSubmit={handleClarifySubmit} />
                            )}
                        </>
                    )}

                    {/* error / terminated banners */}
                    {linsight?.taskError && (
                        <div className="my-2 flex items-start gap-2 rounded-xl border border-red-100 bg-red-50/60 p-3 text-sm text-red-600">
                            <CircleAlert size={16} className="mt-0.5 shrink-0" />
                            <span className="whitespace-pre-wrap break-words">{linsight.taskError}</span>
                        </div>
                    )}
                    {stopped && !linsight?.taskError && (
                        <div className="my-2 flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-500">
                            <OctagonX size={16} className="shrink-0" />
                            {localize('com_linsight_task_terminated')}
                        </div>
                    )}

                    {/* ── artifacts area (P4): report link / answer markdown / file card ── */}
                    {completed && (
                        <div data-slot="execution-artifacts" className="mt-4">
                            <ResultSection
                                answer={linsight?.output_result?.answer}
                                files={fileList}
                                versionId={versionId}
                                onPreview={(file) => artifactsPanel.openPreview(file)}
                            />
                        </div>
                    )}
                </div>
            </div>

            {/* ── footer: waiting hint + task panel + unified input ─────────── */}
            <div className="mx-auto w-full max-w-[800px] shrink-0 px-4 pb-4">
                {pendingInput && (
                    <div className="mb-2 flex items-center gap-2 rounded-lg bg-blue-50 px-3 py-1.5 text-xs text-blue-600">
                        <span className="size-1.5 animate-pulse rounded-full bg-blue-500" />
                        {localize('com_linsight_waiting_your_input')}
                    </div>
                )}
                <TaskPanel tasks={tasks} completed={completed} />
                {isSharePage ? (
                    (completed || stopped) && shareControls
                ) : (
                    <TaskModeInput
                        conversationId={conversationId || linsight?.session_id || 'new'}
                        disabled={running || !!pendingInput}
                    />
                )}
            </div>

            {/* ── right-side area: workspace drawer / file preview (mutually exclusive) ── */}
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
