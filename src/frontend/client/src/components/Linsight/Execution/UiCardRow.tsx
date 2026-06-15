/**
 * F035 Track H (P3): ui_card step row (step_type=ui_card, e.g.
 * emit_research_card; spec §3). Registered card names may get bespoke
 * rendering later (P4); every unregistered name degrades to a plain
 * parameter-text dump per spec.
 */
import { FileText, Send } from 'lucide-react';
import { cn } from '~/utils';
import { detailTextCls, formatStepParams, RunningSpinner, StepRow } from './StepRow';
import type { MergedStep } from './stepUtils';

/**
 * name -> bespoke renderer registry. Intentionally empty until P4 wires real
 * card renderers; everything therefore takes the parameter-text fallback.
 */
const UI_CARD_REGISTRY: Record<string, (step: MergedStep) => JSX.Element> = {};

export function UiCardRow({ step }: { step: MergedStep }) {
    const renderRegistered = UI_CARD_REGISTRY[step.name];
    const paramsText = formatStepParams(step.params);
    return (
        <StepRow
            icon={step.running ? <RunningSpinner /> : <Send size={14} className="text-[#333]" />}
            title={step.name}
            running={step.running}
        >
            {renderRegistered ? (
                renderRegistered(step)
            ) : (
                <>
                    {step.callReason && <p className={cn(detailTextCls, 'text-gray-600')}>{step.callReason}</p>}
                    {paramsText && <p className={detailTextCls}>{paramsText}</p>}
                    {step.extraInfo?.file_info?.file_name && (
                        <p className="mt-1 flex items-center gap-1.5 text-xs text-gray-600">
                            <FileText size={12} className="shrink-0 text-blue-400" />
                            {String(step.extraInfo.file_info.file_name)}
                        </p>
                    )}
                </>
            )}
        </StepRow>
    );
}
