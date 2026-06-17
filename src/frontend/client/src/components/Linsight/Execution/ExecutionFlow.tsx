/**
 * F035 Track H (P3): the new conversational execution view (spec §0/§3) —
 * replaces the legacy SOPEditor/TaskFlow split panes. Top-down flow:
 *   user question bubble → step rows (appended as WS events stream in) →
 *   artifacts area (P4 slot) → footer: task checklist panel + unified input.
 * Everything renders from the Recoil linsight store keyed by versionId; the
 * WS hook (task-message-stream) is mounted here so the event pump stays alive
 * after the old TaskFlow stops rendering.
 */
import { CircleAlert, OctagonX } from 'lucide-react';
import { useMemo, useRef } from 'react';
import { SopStatus } from '~/store/linsight';
import { FilePreviewPanel } from '~/components/Linsight/Artifacts/FilePreviewPanel';
import { ResultSection } from '~/components/Linsight/Artifacts/ResultSection';
import { WorkspaceDrawer } from '~/components/Linsight/Artifacts/WorkspaceDrawer';
import { useArtifactsPanel } from '~/components/Linsight/Artifacts/useArtifactsPanel';
import { type ArtifactFile, toUploadedArtifacts } from '~/components/Linsight/Artifacts/artifactUtils';
import { TaskModeInput } from '~/components/Linsight/Input/TaskModeInput';
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { useLinsightWebSocket } from '~/hooks/Websocket';
import { useLinsightQueuePolling } from '~/hooks/useLinsightQueuePolling';
import { useAutoScroll } from '~/hooks/useAutoScroll';
import { useLocalize } from '~/hooks';
import { ClarifyCard } from './ClarifyCard';
import { ConversationRound } from './ConversationRound';
import { IntentRow } from './IntentRow';
import { LegacySopRow } from './LegacySopRow';
import { PlanningRow } from './PlanningRow';
import { QueueCard } from './QueueCard';
import { StepList } from './StepList';
import { TaskPanel } from './TaskPanel';
import { TaskStepRow, type ExecTask } from './TaskStepRow';
import { isTaskStarted } from './stepUtils';
import type { ExecStepEventData } from './stepUtils';

interface ExecutionFlowProps {
    versionId: string;
    /** conversation id for the input's per-session memory */
    conversationId?: string;
    isSharePage?: boolean;
    /** Historical linsight session opened from the home list (flowType 20 →
        /linsight/:id). The follow-up / continuation flow now lives in the daily
        /c chat, so the standalone viewer is read-only: render the flow but hide
        the bottom input (display-only, cannot be used). */
    readOnly?: boolean;
    /** workspace/preview panel state — lifted to Sop/index so the Header's
        workspace button drives the same drawer */
    artifactsPanel: ReturnType<typeof useArtifactsPanel>;
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

export function ExecutionFlow({ versionId, conversationId, isSharePage = false, readOnly = false, artifactsPanel }: ExecutionFlowProps) {
    const localize = useLocalize();
    const { getLinsight, continueConversation } = useLinsightManager();
    // Mount the WS pump here (the legacy TaskFlow used to own it).
    const { stop, sendInput } = useLinsightWebSocket(versionId);

    const linsight = getLinsight(versionId);
    const tasks: ExecTask[] = (linsight?.tasks as any) || [];
    const sessionSteps: ExecStepEventData[] = (linsight as any)?.sessionSteps || [];
    const status = linsight?.status;
    const running = status === SopStatus.Running;
    const completed = status === SopStatus.completed || status === SopStatus.FeedbackCompleted;
    const stopped = status === SopStatus.Stoped;
    // Poll queue-status while queued (running but no execution output yet); the
    // badge clears when the worker picks us up (index → 0) or steps arrive.
    const noProgressYet = !tasks.length && !sessionSteps.length;
    useLinsightQueuePolling(versionId, running && noProgressYet);
    // Gate on noProgressYet too: once steps/tasks arrive polling stops and the
    // last-polled queueCount may stay stale >0, so this prevents the queue card
    // from lingering next to real task rows.
    const queueing = running && noProgressYet && (linsight?.queueCount || 0) > 0;

    // P4 artifacts: output files + the shared right-side panel (workspace/preview)
    const fileList: ArtifactFile[] = (linsight?.file_list as ArtifactFile[]) || [];
    // Workspace drawer shows both zones: user-uploaded sources + agent deliverables.
    const uploadedFiles = useMemo(
        () => toUploadedArtifacts(linsight?.files as any[]),
        [linsight?.files],
    );
    const workspaceFiles = useMemo(() => [...uploadedFiles, ...fileList], [uploadedFiles, fileList]);

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
            {/* ── conversational flow ─────────────────────────────────────── */}
            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto scroll-hover">
                <div className="mx-auto w-full max-w-[800px] px-4 pb-6 pt-4">
                    {/* F035 multi-turn: completed prior rounds, stacked above the
                        active round so the conversation reads top-to-bottom. */}
                    {(linsight?.history || []).map((round, i) => (
                        <ConversationRound
                            key={`round_${i}`}
                            round={round}
                            versionId={versionId}
                            onPreview={(file) => artifactsPanel.openPreview(file)}
                        />
                    ))}

                    {/* user question bubble (active round) */}
                    {linsight?.question && (
                        <div className="mb-4 flex justify-end">
                            <div className="max-w-[80%] whitespace-pre-wrap rounded-[12px] bg-[#F4F4F4] px-4 py-3 text-[14px] leading-relaxed text-[#212121]">
                                {linsight.question}
                            </div>
                        </div>
                    )}

                    {/* legacy SOP document (read-only, pre-F035 sessions only) */}
                    <LegacySopRow sop={linsight?.sop} />

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

                            {/* task rows with nested sub-step flows — only tasks
                                execution has reached; not-started ones stay in TaskPanel. */}
                            {tasks.filter((task) => isTaskStarted(task.status)).map((task) => (
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
                    <div className="mb-2 flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs text-gray-800">
                        <span className="size-1.5 animate-pulse-scale rounded-full bg-gray-700" />
                        {localize('com_linsight_waiting_your_input')}
                    </div>
                )}
                {/* Design (Figma 12221-40080/40081): card inset 24px each side
                    relative to the input, 12px gap above it. */}
                <div className="px-6 pb-3">
                    <TaskPanel tasks={tasks} completed={completed} />
                </div>
                {/* Share pages AND historical sessions are read-only — no input.
                    Continuation now happens in the daily /c chat; the standalone
                    linsight viewer only displays ("make same style" removed, F035). */}
                {!isSharePage && !readOnly && (
                    <TaskModeInput
                        // The landing route URL is rewritten via history.replaceState after the
                        // first submit, so react-router's `conversationId` stays 'new'. Treat
                        // 'new'/empty as "no real id yet" and fall back to the live session_id,
                        // otherwise follow-up rounds drop session_id and spawn a new session.
                        conversationId={
                            conversationId && conversationId !== 'new'
                                ? conversationId
                                : linsight?.session_id || 'new'
                        }
                        disabled={running || !!pendingInput}
                        // F035 multi-turn: a send here continues THIS conversation
                        // (same session_version + agent thread) instead of starting
                        // a new session. versionId is the live session_version id.
                        onFollowUp={(question) => continueConversation(versionId, question)}
                    />
                )}
            </div>

            {/* ── right-side area: workspace drawer / file preview (mutually exclusive) ── */}
            <WorkspaceDrawer
                open={artifactsPanel.workspaceOpen}
                onOpenChange={artifactsPanel.setWorkspaceOpen}
                files={workspaceFiles}
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
