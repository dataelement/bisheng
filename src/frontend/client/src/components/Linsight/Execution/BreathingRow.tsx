/**
 * Unified "breathing" activity row for the task-mode execution stream.
 *
 * Collapses the three previously-scattered live indicators (PlanningRow ×2 and
 * the inline "generating results" row) into one component with a single activity
 * language: one `animate-pulse` dot + a short status line. Shared by both
 * carriers (ExecutionFlow full-page view + TaskTurnPanel chat-embedded view),
 * which keeps the live feedback identical across surfaces.
 *
 * State → copy mapping (all keys pre-existing):
 *  - planning    → com_linsight_planning   ("Planning tasks")
 *  - researching → com_linsight_executing  ("Working")
 *  - generating  → com_linsight_generating ("Generating results, please wait…")
 */
import { useLocalize } from '~/hooks';

type BreathingState = 'planning' | 'researching' | 'generating';

// state → localize key (single source of truth for the activity copy).
const STATE_I18N: Record<BreathingState, string> = {
    planning: 'com_linsight_planning',
    researching: 'com_linsight_executing',
    generating: 'com_linsight_generating',
};

interface BreathingRowProps {
    /** which live phase to surface; drives the localized copy */
    state: BreathingState;
}

export function BreathingRow({ state }: BreathingRowProps) {
    const localize = useLocalize();
    return (
        <div className="flex items-center gap-2 py-1.5 text-sm text-[#999999]">
            <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-[#999999]" />
            <span>{localize(STATE_I18N[state])}</span>
        </div>
    );
}
