/**
 * F035 multi-turn: read-only renderer for ONE completed conversation round.
 * The active (in-flight) round keeps its own inline markup in ExecutionFlow;
 * this renders each snapshot in `linsight.history` above it so the whole
 * conversation reads top-to-bottom as Q → steps/tasks → answer, repeated per
 * round. No live wiring (no pendingInput / planning / WS) — these rounds are
 * finished, but they DO surface their own terminal banner (stopped / error)
 * the same way the active round does.
 */
import { OctagonX } from 'lucide-react';
import { SopStatus } from '~/store/linsight';
import type { LinsightRoundSnapshot } from '~/store/linsight';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { ResultSection } from '~/components/Linsight/Artifacts/ResultSection';
import { useLocalize } from '~/hooks';
import { ExecutionLiveContext } from './executionLive';
import { ExecutionTimeline } from './ExecutionTimeline';
import { ResultPanel } from './ResultPanel';
import { TaskErrorCard } from './TaskErrorCard';
import { TaskStepRow, type ExecTask } from './TaskStepRow';
import type { ExecStepEventData } from './stepUtils';
import { isTaskStarted } from './stepUtils';

interface ConversationRoundProps {
    round: LinsightRoundSnapshot;
    versionId: string;
    onPreview: (file: ArtifactFile) => void;
}

export function ConversationRound({ round, versionId, onPreview }: ConversationRoundProps) {
    const localize = useLocalize();
    const sessionSteps: ExecStepEventData[] = round.sessionSteps || [];
    const tasks: ExecTask[] = (round.tasks as any) || [];
    const files: ArtifactFile[] = (round.file_list as ArtifactFile[]) || [];
    const stopped = round.status === SopStatus.Stoped;

    return (
        // A historical round is always finished — force non-live so nothing
        // renders a stuck "running" ticker.
        <ExecutionLiveContext.Provider value={false}>
        <div className="border-b border-dashed border-gray-200 pb-4 mb-4">
            {/* user question bubble */}
            {round.question && (
                <div className="mb-4 flex justify-end">
                    <div className="max-w-[80%] whitespace-pre-wrap rounded-[12px] bg-[#F4F4F4] px-4 py-3 text-[14px] leading-relaxed text-[#212121]">
                        {round.question}
                    </div>
                </div>
            )}

            {/* an answered clarify renders as an inline IntentRow at its
                chronological position inside the timeline (时序内联). */}
            <ExecutionTimeline history={sessionSteps} />

            {tasks.filter((task) => isTaskStarted(task.status)).map((task) => (
                <TaskStepRow key={task.id} task={task} />
            ))}

            {/* terminal banners — mirror the active round (no retry: history is
                read-only and the next round already moved on) */}
            {round.taskError && (
                <TaskErrorCard
                    errorType={round.taskErrorInfo?.error_type}
                    detail={round.taskErrorInfo?.detail}
                    fallbackMessage={round.taskError}
                />
            )}
            {stopped && !round.taskError && (
                <div className="my-2 flex items-center gap-2 rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500">
                    <OctagonX size={16} className="shrink-0" />
                    {localize('com_linsight_task_terminated')}
                </div>
            )}

            {round.output_result?.answer && (
                <ResultPanel>
                    <ResultSection
                        answer={round.output_result.answer}
                        files={files}
                        versionId={versionId}
                        onPreview={onPreview}
                    />
                </ResultPanel>
            )}
        </div>
        </ExecutionLiveContext.Provider>
    );
}
