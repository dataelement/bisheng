/**
 * F035 Track H (P3): think_tool step row (step_type=thinking, spec §3).
 * Output streams across frames (extra_info.is_thinking); stepUtils already
 * concatenates the chunks, this row just renders the text when expanded.
 */
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { detailTextCls, RunningSpinner, StepRow } from './StepRow';
import type { MergedStep } from './stepUtils';

export function ThinkingRow({ step }: { step: MergedStep }) {
    const localize = useLocalize();
    return (
        <StepRow
            icon={step.running ? <RunningSpinner /> : <Outlined.Bulb size={14} className="text-[#333]" />}
            title={step.name || localize('com_linsight_thinking')}
            running={step.running}
            titleClassName="text-gray-500"
        >
            <p className={cn(detailTextCls, 'max-h-60 overflow-y-auto')}>{step.output}</p>
        </StepRow>
    );
}
