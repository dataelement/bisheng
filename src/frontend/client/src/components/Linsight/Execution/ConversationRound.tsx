/**
 * F035 multi-turn: read-only renderer for ONE completed conversation round.
 * The active (in-flight) round keeps its own inline markup in ExecutionFlow;
 * this renders each snapshot in `linsight.history` above it so the whole
 * conversation reads top-to-bottom as Q → steps/tasks → answer, repeated per
 * round. No live wiring (no pendingInput / planning / WS) — these rounds are
 * finished.
 */
import type { LinsightRoundSnapshot } from '~/store/linsight';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { ResultSection } from '~/components/Linsight/Artifacts/ResultSection';
import { IntentRow } from './IntentRow';
import { StepList } from './StepList';
import { TaskStepRow, type ExecTask } from './TaskStepRow';
import type { ExecStepEventData } from './stepUtils';
import { isTaskStarted } from './stepUtils';

interface ConversationRoundProps {
    round: LinsightRoundSnapshot;
    versionId: string;
    onPreview: (file: ArtifactFile) => void;
}

export function ConversationRound({ round, versionId, onPreview }: ConversationRoundProps) {
    const sessionSteps: ExecStepEventData[] = round.sessionSteps || [];
    const tasks: ExecTask[] = (round.tasks as any) || [];
    const answeredInputs = sessionSteps.filter(
        (s) => s?.step_type === 'call_user_input' && (s as any)?.is_completed,
    );
    const files: ArtifactFile[] = (round.file_list as ArtifactFile[]) || [];

    return (
        <div className="border-b border-dashed border-gray-200 pb-4 mb-4">
            {/* user question bubble */}
            {round.question && (
                <div className="mb-4 flex justify-end">
                    <div className="max-w-[80%] whitespace-pre-wrap rounded-[12px] bg-[#F4F4F4] px-4 py-3 text-[14px] leading-relaxed text-[#212121]">
                        {round.question}
                    </div>
                </div>
            )}

            {answeredInputs.map((entry, i) => (
                <IntentRow key={`h_intent_${i}`} data={entry} />
            ))}

            <StepList history={sessionSteps} />

            {tasks.filter((task) => isTaskStarted(task.status)).map((task) => (
                <TaskStepRow key={task.id} task={task} />
            ))}

            {round.output_result?.answer && (
                <div className="mt-4">
                    <ResultSection
                        answer={round.output_result.answer}
                        files={files}
                        versionId={versionId}
                        onPreview={onPreview}
                    />
                </div>
            )}
        </div>
    );
}
