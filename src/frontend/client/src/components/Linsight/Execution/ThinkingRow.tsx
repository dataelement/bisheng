/**
 * F035 Track H (P3): think_tool step row (step_type=thinking, spec §3).
 * Output streams across frames (extra_info.is_thinking); stepUtils already
 * concatenates the chunks, this row just renders the text when expanded.
 */
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { ACCENT, BODY, MUTED } from './execTokens';
import { detailTextCls, StepRow } from './StepRow';
import { firstLine, type MergedStep } from './stepUtils';

export function ThinkingRow({ step }: { step: MergedStep }) {
    const localize = useLocalize();
    // step.name is the backend-stamped literal 'thinking' (always English — a
    // localization break-through). Prefer a one-line fingerprint of the merged
    // thinking passage so the collapsed header carries real, localized content;
    // fall back to the localized label when the output is empty.
    const title = firstLine(step.output) || localize('com_linsight_thinking');
    // Unified icon system (§1.3): running → Accent Loading spinner; done → Muted
    // Bulb. Single source (bisheng-icons Outlined.*), 16px, color by state.
    const icon = step.running
        ? <Outlined.Loading size={16} className="animate-spin" style={{ color: ACCENT }} />
        : <Outlined.Bulb size={16} style={{ color: MUTED }} />;
    return (
        <StepRow icon={icon} title={title} running={step.running}>
            <p className={cn(detailTextCls, 'max-h-60 overflow-y-auto')} style={{ color: BODY }}>{step.output}</p>
        </StepRow>
    );
}
