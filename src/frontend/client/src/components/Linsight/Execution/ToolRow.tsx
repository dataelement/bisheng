/**
 * F035 Track H (P3): tool-call step row (step_type=tool, spec §3).
 * Header: icon + tool name; expanded: call reason + input params + output.
 */
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { detailTextCls, formatStepParams, RunningSpinner, StepRow, stepTypeIcon } from './StepRow';
import type { MergedStep } from './stepUtils';

export function ToolRow({ step }: { step: MergedStep }) {
    const localize = useLocalize();
    const paramsText = formatStepParams(step.params);
    return (
        <StepRow
            icon={step.running ? <RunningSpinner /> : stepTypeIcon(step.name)}
            title={step.name}
            running={step.running}
        >
            {step.callReason && <p className={cn(detailTextCls, 'text-gray-600')}>{step.callReason}</p>}
            {paramsText && (
                <div className="mt-1">
                    <p className="text-xs font-medium text-gray-400">{localize('com_linsight_step_input')}</p>
                    <p className={cn(detailTextCls, 'max-h-40 overflow-y-auto')}>{paramsText}</p>
                </div>
            )}
            {step.output && (
                <div className="mt-1">
                    <p className="text-xs font-medium text-gray-400">{localize('com_linsight_step_output')}</p>
                    <p className={cn(detailTextCls, 'max-h-40 overflow-y-auto')}>{step.output}</p>
                </div>
            )}
        </StepRow>
    );
}
