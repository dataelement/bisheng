/**
 * F035 Track H (P3): breathing "working" row (spec §3). Shown while the agent is
 * planning (running, no todo list yet) and — with an explicit `label` — to bridge
 * the gaps between tasks (todos generated but next task not started, or wrap-up)
 * so the run never looks frozen when no per-task spinner is visible. The breathing
 * dot signals active output.
 */
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { RunningSpinner } from './StepRow';

export function PlanningRow({ label }: { label?: string }) {
    const localize = useLocalize();
    return (
        <div className="flex items-center gap-2 px-2 py-1.5 text-sm text-[#8C8C8C]">
            <Outlined.ListSuccess className="size-4 text-[#1A1A1A]" />
            <span>{label ?? localize('com_linsight_planning')}</span>
            <RunningSpinner />
        </div>
    );
}
