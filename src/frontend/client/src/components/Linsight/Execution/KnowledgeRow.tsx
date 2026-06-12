/**
 * F035 Track H (P3): knowledge-retrieval step row (step_type=knowledge, spec §3
 * fig.11). Expanded: hit entries (icon + title) best-effort parsed from
 * extra_info.file_info / output; plain output text as fallback.
 */
import { FileText, ScrollText } from 'lucide-react';
import { cn } from '~/utils';
import { detailTextCls, RunningSpinner, StepRow } from './StepRow';
import type { MergedStep } from './stepUtils';

/** Best-effort hit list: extra_info.file_info entry + JSON-parseable output items. */
function knowledgeHits(step: MergedStep): { title: string }[] {
    const hits: { title: string }[] = [];
    const fileInfo = step.extraInfo?.file_info;
    if (fileInfo?.file_name) hits.push({ title: String(fileInfo.file_name) });
    try {
        const parsed = JSON.parse(step.output);
        if (Array.isArray(parsed)) {
            parsed.forEach((item: any) => {
                const title = item?.title || item?.file_name || item?.name;
                if (title) hits.push({ title: String(title) });
            });
        }
    } catch {
        // output is plain text (fixture shape) — rendered below the hit list
    }
    return hits;
}

export function KnowledgeRow({ step }: { step: MergedStep }) {
    const hits = knowledgeHits(step);
    return (
        <StepRow
            icon={step.running ? <RunningSpinner /> : <ScrollText size={14} className="text-gray-400" />}
            title={step.name}
            running={step.running}
        >
            {step.callReason && <p className={cn(detailTextCls, 'text-gray-600')}>{step.callReason}</p>}
            {step.params?.query != null && <p className={detailTextCls}>{String(step.params.query)}</p>}
            {hits.length > 0 && (
                <ul className="mt-1 space-y-1">
                    {hits.map((hit, i) => (
                        <li key={i} className="flex items-center gap-1.5 text-xs text-gray-600">
                            <FileText size={12} className="shrink-0 text-blue-400" />
                            <span className="truncate">{hit.title}</span>
                        </li>
                    ))}
                </ul>
            )}
            {step.output && <p className={cn(detailTextCls, 'mt-1 max-h-40 overflow-y-auto')}>{step.output}</p>}
        </StepRow>
    );
}
