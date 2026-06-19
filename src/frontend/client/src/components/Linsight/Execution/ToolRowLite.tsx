/**
 * ToolRowLite — task-mode tool / knowledge step row, isomorphic to the daily /c
 * ToolCallDisplay verb-phrase language but built on the shared task-mode
 * primitives (CollapsibleTimelineItem + TimelineRail). It does NOT import or
 * touch any Chat/Messages component — the verb-phrase map and detail-text tokens
 * are copied here (the North Star `BUILTIN_TOOL_I18N` is not exported).
 *
 * Header: a verb phrase ("已联网搜索" / "已检索知识" / "已写入文件" / "已更新任务清单"
 * / "已使用 X"), running → "正在调用 X" with a spinner rail. Expanded body keeps
 * the existing input/output sections (no MergedStep→AgentToolCall adapter, so a
 * bare-string output never degrades into a single result chip).
 */
import { Outlined } from 'bisheng-icons';
import { useState, type FC } from 'react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import CollapsibleTimelineItem from './CollapsibleTimelineItem';
import { ACCENT, BODY, MUTED } from './execTokens';
import { detailTextCls, formatStepParams, stepTypeIcon } from './StepRow';
import type { MergedStep } from './stepUtils';

export interface ToolRowLiteProps {
    step: MergedStep;
}

/**
 * Verb-phrase map copied from the North Star ToolCallDisplay (BUILTIN_TOOL_I18N
 * is not exported there). Built-in tools resolve to a finished verb phrase; any
 * other tool falls through to "已使用 {name}". Keyed by lowercased tool name so
 * both `search_knowledge_base` and `search_knowledge_bases` resolve.
 */
const TOOL_VERB_I18N: Record<string, string> = {
    web_search: '已联网搜索',
    search_knowledge_base: '已检索知识',
    search_knowledge_bases: '已检索知识',
    write_file: '已写入文件',
    write_todos: '已更新任务清单',
};

/** Detail text class (color applied via the Body token at the call site). */
const DETAIL_TEXT = 'whitespace-pre-wrap break-words text-xs leading-5';

/**
 * Recolor stepTypeIcon's glyph to the Muted token (§1.3 — single color by state,
 * not by icon). stepTypeIcon hardcodes text-[#333]; this arbitrary descendant
 * selector overrides the inner svg color without editing StepRow.
 */
const MUTED_GLYPH = '[&>svg]:text-[#8A8A8A]';

/** Resolve the running / finished verb-phrase title for a tool step. */
function resolveTitle(step: MergedStep, localize: ReturnType<typeof useLocalize>): string {
    const key = (step.name || '').toLowerCase();
    const verb = TOOL_VERB_I18N[key];
    if (step.running) {
        // Mirror ToolCallDisplay inflight phrasing; verb maps are past-tense, so
        // running steps use the generic "正在调用 X" form against the raw name.
        return `正在调用 ${step.name || localize('com_tools_generic_fallback')}`;
    }
    if (verb) return verb;
    // Fallback: "已使用 {name}" (North Star generic-tool phrasing).
    return `已使用 ${step.name || localize('com_tools_generic_fallback')}`;
}

const ToolRowLite: FC<ToolRowLiteProps> = ({ step }) => {
    const localize = useLocalize();
    // Default COLLAPSED to a single verb-phrase line (入参/结果 on demand). The
    // parent group already stays expanded while it's the active episode; keeping
    // each tool row as one quiet line stops the expanded group from becoming a wall
    // of streamed tool output and removes the only remaining in-group height churn
    // (a row auto-expanding the moment its output streamed in). Row-level open is
    // local; the parent DeepStepGroup owns the group-level fold.
    const [open, setOpen] = useState<boolean>(false);

    const paramsText = formatStepParams(step.params);
    const hasDetails = !!(step.callReason || paramsText || step.output);

    const title = resolveTitle(step, localize);
    // Unified icon system (§1.3): running → Accent Loading spinner; done →
    // stepTypeIcon recolored to Muted via the descendant selector.
    const icon = step.running
        ? <Outlined.Loading size={16} className="animate-spin" style={{ color: ACCENT }} />
        : <span className={cn('flex', MUTED_GLYPH)}>{stepTypeIcon(step.name)}</span>;

    return (
        <CollapsibleTimelineItem
            icon={icon}
            label={title}
            streaming={step.running}
            // Non-collapsible rows still render the rail/title; clicking is a
            // no-op when there is no detail to reveal.
            open={hasDetails && open}
            onToggle={(next) => hasDetails && setOpen(next)}
        >
            {step.callReason && <p className={DETAIL_TEXT} style={{ color: BODY }}>{step.callReason}</p>}
            {paramsText && (
                <div className="mt-1">
                    <p className="text-xs font-medium" style={{ color: MUTED }}>{localize('com_linsight_step_input')}</p>
                    <p className={cn(detailTextCls, 'max-h-40 overflow-y-auto')} style={{ color: BODY }}>{paramsText}</p>
                </div>
            )}
            {step.output && (
                <div className="mt-1">
                    <p className="text-xs font-medium" style={{ color: MUTED }}>{localize('com_linsight_step_output')}</p>
                    <p className={cn(DETAIL_TEXT, 'max-h-40 overflow-y-auto')} style={{ color: BODY }}>{step.output}</p>
                </div>
            )}
        </CollapsibleTimelineItem>
    );
};

ToolRowLite.displayName = 'ToolRowLite';

// Exported both ways: the Execution primitives (CollapsibleTimelineItem etc.)
// use default exports, while ExecutionTimeline imports a named member. Provide
// both so either consumer compiles without cross-file churn.
export { ToolRowLite };
export default ToolRowLite;
