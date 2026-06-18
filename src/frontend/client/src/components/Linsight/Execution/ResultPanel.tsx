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

interface ResultPanelProps {
    /** the terminal deliverable (typically <ResultSection />) */
    children: ReactNode;
}

export function ResultPanel({ children }: ResultPanelProps) {
    const localize = useLocalize();
    return (
        <div data-slot="execution-result" className="mt-6 border-t border-gray-200 pt-4">
            <div className="mb-3 flex items-center gap-2">
                <Outlined.DoubleCheck size={16} className="shrink-0 text-[#212121]" />
                <span className="text-sm font-medium text-[#212121]">{localize('com_linsight_task_completed')}</span>
            </div>
            {children}
        </div>
    );
}
