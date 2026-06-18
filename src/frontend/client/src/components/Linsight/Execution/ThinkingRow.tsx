/**
 * F035 Track H (P3): think_tool step row (step_type=thinking, spec §3).
 * Output streams across frames (extra_info.is_thinking); stepUtils already
 * concatenates the chunks, this row just renders the text when expanded.
 */
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { detailTextCls, RunningSpinner, StepRow } from './StepRow';
import { firstLine, type MergedStep } from './stepUtils';

export function ThinkingRow({ step }: { step: MergedStep }) {
    const localize = useLocalize();
    // step.name is the backend-stamped literal 'thinking' (always English — a
    // localization break-through). Prefer a one-line fingerprint of the merged
    // thinking passage so the collapsed header carries real, localized content;
    // fall back to the localized label when the output is empty.
    const title = firstLine(step.output) || localize('com_linsight_thinking');
    return (
        <StepRow
            icon={step.running ? <RunningSpinner /> : <Outlined.Bulb size={16} className="text-[#333]" />}
            title={title}
            running={step.running}
        >
            <p className={cn(detailTextCls, 'max-h-60 overflow-y-auto text-[#818181]')}>{step.output}</p>
        </StepRow>
    );
}
