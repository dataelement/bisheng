/**
 * DeepStepGroup — task-mode "deep thinking" group, isomorphic to the daily /c
 * DeepThinkingGroup. It aggregates one episode of consecutive top-level steps
 * (thinking + tool + knowledge) into a single collapsible group whose header
 * reads "正在深度思考（已用 N 秒）..." while live, or "已深度思考（用时 N 秒）"
 * once closed.
 *
 * Stable-label scheme (reverted from the narration experiment): the header is the
 * plain duration label — predictable and quiet — fronted by a consistent rail
 * icon so EVERY timeline node carries one (fixing "only the subagent group has an
 * icon"). The rail + icon + gap exactly mirror SubagentTeamGroup, so all
 * top-level nodes share one left spine (no more ragged left edge).
 *
 * Icon color regime (§1.3): running → Accent (the single live highlight) + the
 * header pulses; done → Muted. The old invisible #C9CDD4 grey is gone.
 *
 * Single-level fold: the expanded body lays out the thinking passages directly as
 * Body-colored text (no inner "思考内容" collapsible) interleaved with tool /
 * knowledge rows in original timeline order. The group shell owns the only
 * open/close state, persisted via useCollapseState (running → open, done →
 * collapsed).
 *
 * It does NOT import or modify any Chat/Messages (daily /c) component — all
 * tokens come from execTokens, the timer math from useElapsedTicker.
 */
import { Outlined } from 'bisheng-icons';
import { useMemo, type FC, type ReactNode } from 'react';
import { useLocalize } from '~/hooks';
import { useCollapseState } from '~/store/linsightCollapse';
import { cn } from '~/utils';
import { ACCENT, BODY, INK, MUTED } from './execTokens';
import { useExecutionLive } from './executionLive';
import { KnowledgeRow } from './KnowledgeRow';
import TimelineRail from './TimelineRail';
import ToolRowLite from './ToolRowLite';
import { formatSeconds, useElapsedTicker } from './useElapsedTicker';
import type { DeepStepGroup as DeepStepGroupData, MergedStep } from './stepUtils';

export interface DeepStepGroupProps {
    group: DeepStepGroupData;
    /**
     * Drilldown context (inside a subagent card): drop the "（用时 N 秒）" duration
     * from the label. Time is a TOP-LEVEL timeline property — the subagent team
     * header already carries the elapsed clause, so repeating it on every nested
     * thinking group is noise. Top-level groups (compact=false) keep their time.
     */
    compact?: boolean;
}

/** A render segment: a stitched thinking passage, or a single tool/knowledge step. */
type Segment =
    | { kind: 'thinking'; key: string; text: string }
    | { kind: 'tool'; key: string; step: MergedStep };

/**
 * Walk the ordered steps, folding each run of consecutive thinking steps into one
 * passage while keeping tool / knowledge steps in place. The deltas are stitched
 * SEAMLESSLY ("") — each thinking chunk already carries its own leading space and
 * the model's own newlines, so a "\n\n" separator would break one continuous
 * reasoning into a blank-line-per-token "poem". mergeAdjacentThinking already
 * collapsed same-ns neighbours upstream; this second pass is defensive and
 * order-preserving.
 */
function buildSegments(steps: MergedStep[]): Segment[] {
    const out: Segment[] = [];
    for (const step of steps) {
        if (step.stepType === 'thinking') {
            const prev = out[out.length - 1];
            if (prev && prev.kind === 'thinking') {
                prev.text = [prev.text, step.output].filter(Boolean).join('');
                continue;
            }
            out.push({ kind: 'thinking', key: step.callId, text: step.output });
            continue;
        }
        out.push({ kind: 'tool', key: step.callId, step });
    }
    return out;
}

const DeepStepGroup: FC<DeepStepGroupProps> = ({ group, compact = false }) => {
    const localize = useLocalize();
    // Gate "running" on the turn being live: a completed/stopped turn means
    // nothing is actually running, so a dangling step (e.g. a safety-blocked
    // subagent that never got its end frame) can't keep this group ticking in a
    // "正在深度思考…" state. Non-live → done label + frozen clock + default collapse.
    const live = useExecutionLive();
    const running = group.running && live;
    // Group-level fold: ONE stable open state per group, persisted to
    // sessionStorage so a manual toggle survives refresh / session switch.
    // Default = running (expanded while live to watch progress; collapsed once
    // done to a single summary line for history review).
    const persistKey = group.steps[0]?.callId ?? '';
    const [open, setOpen] = useCollapseState(persistKey, running);

    // Timestamps on MergedStep are second-level ints (BaseEvent.timestamp); the
    // ticker math is in milliseconds, so scale up here.
    const startMs = group.startedAt != null ? group.startedAt * 1000 : null;
    const endMs = group.endedAt != null ? group.endedAt * 1000 : null;
    const { elapsedMs } = useElapsedTicker(startMs, endMs, running);

    // Stable duration label — the i18n key bakes in "（用时 {{0}} 秒）", so feed it
    // the bare number (formatSeconds). 0 elapsed still reads "用时 0 秒" rather than
    // an empty header, keeping the label shape constant.
    const label = useMemo<string>(() => {
        // Drop the "（用时 N 秒）" clause when nested (compact) OR when the measured
        // span is 0. A single-frame thinking passage is persisted as ONE row with
        // ONE second-level timestamp, so startedAt == endedAt → elapsed 0; printing
        // "用时 0.0 秒" for a paragraph of reasoning is misleading (the real time is
        // simply unmeasurable at second resolution). Show the bare phrase instead.
        if (compact || elapsedMs <= 0) {
            return localize(
                running
                    ? 'com_linsight_deep_thinking_running_compact'
                    : 'com_linsight_deep_thinking_done_compact',
            );
        }
        const seconds = formatSeconds(elapsedMs);
        return localize(
            running ? 'com_linsight_deep_thinking_running' : 'com_linsight_deep_thinking_done',
            { 0: seconds },
        );
    }, [compact, elapsedMs, running, localize]);

    const segments = useMemo(() => buildSegments(group.steps), [group.steps]);

    const body: ReactNode = segments.map((seg) => {
        if (seg.kind === 'thinking') {
            if (!seg.text) return null;
            // No per-passage title (single-level fold) — Body-colored direct text.
            return (
                <p
                    key={seg.key}
                    className="whitespace-pre-wrap break-words text-xs leading-5"
                    style={{ color: BODY }}
                >
                    {seg.text}
                </p>
            );
        }
        // Knowledge steps keep their richer hit-list row; everything else is a
        // lite tool row. Both preserve original timeline order.
        if (seg.step.stepType === 'knowledge') {
            return <KnowledgeRow key={seg.key} step={seg.step} />;
        }
        return <ToolRowLite key={seg.key} step={seg.step} />;
    });

    return (
        <div className="flex w-full min-w-0 gap-2 animate-thinking-appear">
            <TimelineRail
                icon={<Outlined.Bulb size={16} style={{ color: running ? ACCENT : MUTED }} />}
                showConnector={open}
            />
            <div className="flex min-w-0 flex-1 flex-col pb-3">
                <button
                    type="button"
                    onClick={() => setOpen(!open)}
                    className={cn(
                        'group flex w-full items-center gap-2 text-left text-sm font-medium leading-[22px]',
                        running && 'animate-pulse',
                    )}
                    style={{ color: INK }}
                >
                    <span className="min-w-0 truncate">{label}</span>
                    <Outlined.Down
                        size={16}
                        className={cn(
                            'shrink-0 transform-gpu transition-transform duration-200',
                            open && 'rotate-180',
                        )}
                        style={{ color: MUTED }}
                    />
                </button>
                <div
                    className={cn('grid transition-all duration-300 ease-out', open && 'mt-2')}
                    style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
                >
                    <div className="min-h-0 overflow-hidden">
                        <div className="flex flex-col gap-1.5">{body}</div>
                    </div>
                </div>
            </div>
        </div>
    );
};

DeepStepGroup.displayName = 'DeepStepGroup';

// Exported both ways: SubagentTrack imports the default, ExecutionTimeline a
// named member. Provide both so either consumer compiles without cross-file churn.
export { DeepStepGroup };
export default DeepStepGroup;
