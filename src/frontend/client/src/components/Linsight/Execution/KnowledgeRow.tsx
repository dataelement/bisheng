/**
 * F035 Track H (P3): knowledge-retrieval step row (step_type=knowledge, spec §3
 * fig.11). Expanded: hit entries (icon + title) best-effort parsed from
 * extra_info.file_info / output; plain output text as fallback.
 */
import { Outlined } from 'bisheng-icons';
import { cn } from '~/utils';
import { ACCENT, BODY, INK, MUTED } from './execTokens';
import { detailTextCls, StepRow } from './StepRow';
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
    // Unified icon system (§1.3): running → Accent Loading spinner; done → Ink
    // BookOpenText (matching the top-level node glyph). Hit-list glyph is the
    // Outlined.File equivalent (lucide FileText removed), 16px Muted as detail.
    const icon = step.running
        ? <Outlined.Loading size={16} className="animate-spin" style={{ color: ACCENT }} />
        : <Outlined.BookOpenText size={16} style={{ color: INK }} />;
    return (
        <StepRow icon={icon} title={step.name} running={step.running}>
            {step.callReason && <p className={detailTextCls} style={{ color: BODY }}>{step.callReason}</p>}
            {step.params?.query != null && <p className={detailTextCls} style={{ color: BODY }}>{String(step.params.query)}</p>}
            {hits.length > 0 && (
                <ul className="mt-1 space-y-1">
                    {hits.map((hit, i) => (
                        <li key={i} className="flex items-center gap-1.5 text-xs" style={{ color: BODY }}>
                            <Outlined.File size={16} className="shrink-0" style={{ color: MUTED }} />
                            <span className="truncate">{hit.title}</span>
                        </li>
                    ))}
                </ul>
            )}
            {step.output && <p className={cn(detailTextCls, 'mt-1 max-h-40 overflow-y-auto')} style={{ color: BODY }}>{step.output}</p>}
        </StepRow>
    );
}
