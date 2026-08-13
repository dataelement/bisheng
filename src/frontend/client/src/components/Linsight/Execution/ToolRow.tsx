/**
 * F035 Track H (P3): tool-call step row (step_type=tool, spec §3).
 * Header: icon + tool name; expanded: call reason + input params + output.
 */
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { INGEST_PHASE_I18N, readIngestProgress } from './execTypes';
import { detailTextCls, formatStepParams, RunningSpinner, StepRow, stepTypeIcon } from './StepRow';
import type { MergedStep } from './stepUtils';

export function ToolRow({ step }: { step: MergedStep }) {
    const localize = useLocalize();
    const paramsText = formatStepParams(step.params);
    // Deferred attachment ingest reports itself as a tool row carrying only counts;
    // the copy is ours (see execTypes). Every other tool row titles itself with the
    // tool's own name, which is already language-neutral.
    const ingest = readIngestProgress(step);
    const title = ingest
        ? localize(INGEST_PHASE_I18N[ingest.phase], { 0: String(ingest.done), 1: String(ingest.total) })
        : step.name;
    return (
        <StepRow
            icon={step.running ? <RunningSpinner /> : stepTypeIcon(step.name)}
            title={title}
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
