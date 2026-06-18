/**
 * DeepStepGroup — task-mode "deep thinking" group, isomorphic to the daily /c
 * DeepThinkingGroup. It aggregates one episode of consecutive top-level steps
 * (thinking + tool + knowledge) into a single collapsible group whose header
 * reads "正在深度思考（已用 N 秒）..." while live or "已深度思考（用时 N 秒）"
 * once closed.
 *
 * It does NOT import or modify any Chat/Messages component — the header tokens,
 * timer math (via useElapsedTicker), and thinking-passage styling are the
 * task-mode-local copies of the North Star tokens.
 *
 * Group-level fold replaces row-level fold (§5.4): the group shell owns ONE
 * open/close state, default-open and NOT bound to running, so live appends never
 * collapse the episode. Inside, consecutive thinking steps are stitched into one
 * "思考内容" passage (joined with a blank line) and tool/knowledge steps render
 * as <ToolRowLite> in original timeline order.
 */
import { Outlined } from 'bisheng-icons';
import { useMemo, useState, type FC, type ReactNode } from 'react';
import { useRecoilValue } from 'recoil';
import { useLocalize } from '~/hooks';
import store from '~/store';
import { cn } from '~/utils';
import CollapsibleTimelineItem from './CollapsibleTimelineItem';
import ToolRowLite from './ToolRowLite';
import { formatSeconds, useElapsedTicker } from './useElapsedTicker';
import type { DeepStepGroup as DeepStepGroupData, MergedStep } from './stepUtils';

export interface DeepStepGroupProps {
    group: DeepStepGroupData;
}

const HEADER_BASE =
    'group flex w-fit items-center gap-1 text-sm font-medium leading-[22px] text-[#212121]';
const HEADER_ICON = 'shrink-0 transform-gpu text-[#999999] transition-transform duration-200';

/** A render segment: a stitched thinking passage, or a single tool/knowledge step. */
type Segment =
    | { kind: 'thinking'; key: string; text: string; running: boolean }
    | { kind: 'tool'; key: string; step: MergedStep };

/**
 * Walk the ordered steps, folding each run of consecutive thinking steps into one
 * passage (joined with a blank line, North Star phrasing) while keeping tool /
 * knowledge steps in place. mergeAdjacentThinking already collapsed same-ns
 * neighbours upstream; this second pass is defensive and order-preserving.
 */
function buildSegments(steps: MergedStep[]): Segment[] {
    const out: Segment[] = [];
    for (const step of steps) {
        if (step.stepType === 'thinking') {
            const prev = out[out.length - 1];
            if (prev && prev.kind === 'thinking') {
                prev.text = [prev.text, step.output].filter(Boolean).join('\n\n');
                prev.running = step.running;
                continue;
            }
            out.push({ kind: 'thinking', key: step.callId, text: step.output, running: step.running });
            continue;
        }
        out.push({ kind: 'tool', key: step.callId, step });
    }
    return out;
}

/**
 * Stitched thinking passage rendered as a "思考内容" collapsible item — a
 * task-mode-local copy of the North Star ThinkingContent (CheckCircle rail +
 * #818181 body), default-open following the user's `showThinking` preference.
 */
const ThinkingPassage: FC<{ text: string; running: boolean }> = ({ text, running }) => {
    const localize = useLocalize();
    const showThinkingDefault = useRecoilValue<boolean>(store.showThinking);
    const [open, setOpen] = useState<boolean>(showThinkingDefault);
    if (!text) return null;
    return (
        <CollapsibleTimelineItem
            icon={<Outlined.CheckCircle size={16} className="shrink-0 text-[#C9CDD4]" />}
            label={localize('com_ui_thoughts')}
            streaming={running}
            open={open}
            onToggle={setOpen}
        >
            <p className="whitespace-pre-wrap text-xs leading-5 text-[#818181]">{text}</p>
        </CollapsibleTimelineItem>
    );
};

const DeepStepGroup: FC<DeepStepGroupProps> = ({ group }) => {
    const localize = useLocalize();
    // Group-level fold: ONE stable open state, default-open and NOT bound to
    // running — live appends only push into `children`, the shell never toggles.
    const [open, setOpen] = useState<boolean>(true);

    // Timestamps on MergedStep are second-level ints (BaseEvent.timestamp); the
    // ticker math is in milliseconds, so scale up here.
    const startMs = group.startedAt != null ? group.startedAt * 1000 : null;
    const endMs = group.endedAt != null ? group.endedAt * 1000 : null;
    const { elapsedMs } = useElapsedTicker(startMs, endMs, group.running);

    const label = useMemo<string>(() => {
        const showDuration = elapsedMs > 0;
        const seconds = formatSeconds(elapsedMs);
        if (group.running) {
            return showDuration
                ? localize('com_linsight_deep_thinking_running', { 0: seconds })
                : localize('com_linsight_deep_thinking_running', { 0: '0' });
        }
        return showDuration
            ? localize('com_linsight_deep_thinking_done', { 0: seconds })
            : localize('com_linsight_deep_thinking_done', { 0: '0' });
    }, [elapsedMs, group.running, localize]);

    const segments = useMemo(() => buildSegments(group.steps), [group.steps]);

    const body: ReactNode = segments.map((seg) =>
        seg.kind === 'thinking' ? (
            <ThinkingPassage key={seg.key} text={seg.text} running={seg.running} />
        ) : (
            <ToolRowLite key={seg.key} step={seg.step} />
        ),
    );

    return (
        <div className="flex w-full min-w-0 flex-col gap-3">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className={cn(HEADER_BASE, group.running && 'animate-pulse')}
            >
                <span>{label}</span>
                <Outlined.Down size={16} className={cn(HEADER_ICON, open && 'rotate-180')} />
            </button>
            <div
                className="grid transition-all duration-300 ease-out"
                style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
            >
                <div className="min-h-0 overflow-hidden">{body}</div>
            </div>
        </div>
    );
};

DeepStepGroup.displayName = 'DeepStepGroup';

// Exported both ways: SubagentTrack imports the default, ExecutionTimeline a
// named member. Provide both so either consumer compiles without cross-file churn.
export { DeepStepGroup };
export default DeepStepGroup;
