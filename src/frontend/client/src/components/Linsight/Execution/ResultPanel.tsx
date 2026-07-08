/**
 * Terminal result container for the task-mode execution stream (peak-end rule).
 *
 * Lifts the final deliverable (ResultSection) out of the homogeneous process
 * flow so the produced artifacts read as the run's peak, not just another step.
 * A top border separates it from the process timeline above, and a ✓ "Task
 * completed" header marks the terminal state. Shared by both carriers
 * (ExecutionFlow / TaskTurnPanel) — the caller still owns ResultSection and
 * passes it as children.
 */
import { Outlined } from 'bisheng-icons';
import type { ReactNode } from 'react';
import { useLocalize } from '~/hooks';
import { MessageFeedbackButtons } from '~/components/Chat/MessageFeedbackButtons';
import { likeLinsightVersion, commentLinsightVersion } from '~/api/linsight';
import { INK } from './execTokens';

interface ResultPanelProps {
    /** the terminal deliverable (typically <ResultSection />) */
    children: ReactNode;
    /** linsight session_version id — the feedback target */
    versionId?: string;
    /** persisted 点赞/点踩 verdict: 0 none / 1 up / 2 down */
    liked?: number;
    /** show 点赞/点踩 (off for read-only / share view) */
    allowFeedback?: boolean;
}

export function ResultPanel({ children, versionId, liked, allowFeedback }: ResultPanelProps) {
    const localize = useLocalize();
    // peak-end (§2.6): a DoubleCheck Ink "task completed" header marks the
    // terminal state and lifts the deliverable out of the homogeneous flow; body
    // is 14px Ink (one notch larger than the process body so the result reads as
    // the run's peak). The old 2px Ink top rule was dropped for a cleaner seam.
    return (
        <div
            data-slot="execution-result"
            className="mt-6 text-sm"
            style={{ color: INK }}
        >
            <div className="mb-3 flex items-center gap-2">
                <Outlined.DoubleCheck size={16} className="shrink-0" style={{ color: INK }} />
                <span className="text-sm font-medium" style={{ color: INK }}>
                    {localize('com_linsight_task_completed')}
                </span>
            </div>
            {children}
            {/* 点赞/点踩 — the task result lives in linsight_session_version, so
                persist via the linsight feedback endpoint keyed by version id
                (best-effort: optimistic UI, backend wiring per PRD). */}
            {allowFeedback && versionId && (
                <div className="mt-3">
                    <MessageFeedbackButtons
                        liked={liked}
                        onLike={(l) => { void likeLinsightVersion(versionId, l).catch(() => {}); }}
                        onDislikeComment={(c) => { void commentLinsightVersion(versionId, c).catch(() => {}); }}
                    />
                </div>
            )}
        </div>
    );
}
