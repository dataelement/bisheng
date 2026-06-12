/**
 * F035 Track H (P3): "planning tasks" row (spec §3) — shown while the agent is
 * still planning (running, no todo list yet). The breathing dot signals
 * active output.
 */
import { AlignLeft } from 'lucide-react';
import { useLocalize } from '~/hooks';

export function PlanningRow() {
    const localize = useLocalize();
    return (
        <div className="flex items-center gap-2 px-2 py-1.5 text-sm text-gray-700">
            <AlignLeft size={14} className="text-gray-400" />
            <span>{localize('com_linsight_planning')}</span>
            {/* breathing dot: scale + fade loop while output is streaming */}
            <span className="size-2 animate-[pulse_1.2s_ease-in-out_infinite] rounded-full bg-blue-500" />
        </div>
    );
}
