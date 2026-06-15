/**
 * F035 Track H (P3): "planning tasks" row (spec §3) — shown while the agent is
 * still planning (running, no todo list yet). The breathing dot signals
 * active output.
 */
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { RunningSpinner } from './StepRow';

export function PlanningRow() {
    const localize = useLocalize();
    return (
        <div className="flex items-center gap-2 px-2 py-1.5 text-sm text-[#8C8C8C]">
            <Outlined.ListSuccess className="size-4 text-[#1A1A1A]" />
            <span>{localize('com_linsight_planning')}</span>
            <RunningSpinner />
        </div>
    );
}
