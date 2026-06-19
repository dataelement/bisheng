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
import { ACCENT, ACTIVITY_I18N, BODY, INK, MUTED } from './execTokens';
import { useExecutionLive } from './executionLive';
import { KnowledgeRow } from './KnowledgeRow';
import TimelineRail from './TimelineRail';
import ToolRowLite from './ToolRowLite';
import { formatSeconds, useElapsedTicker } from './useElapsedTicker';
import { narrationFromSteps, summarizeActivity } from './stepUtils';
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
    /**
     * (R3 完全拆平 2026-06) When set, this group IS a single subagent rendered as
     * its own top-level segment (no team shell). The header carries the delegation
     * goal + activity summary and a distinct rail icon so subagent work is still
     * legible at a glance even after the team grouping is dissolved.
     */
    subagent?: { goal: string; idx: number };
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

const DeepStepGroup: FC<DeepStepGroupProps> = ({ group, compact = false, subagent }) => {
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

    // R1 (段流重构 2026-06): the segment header is the ACTIVITY SUMMARY of what
    // this episode did ("检索知识库 3 次 · 读 2 文件") — built from summarizeActivity,
    // which excludes thinking / write_todos / ls / ask_user. A pure-reasoning
    // segment yields no activity and falls back to the plain 深度思考 label.
    const activityText = useMemo<string>(() => {
        const activity = summarizeActivity(group.steps);
        if (!activity.length) return '';
        return activity
            .map((a) => localize(ACTIVITY_I18N[a.category], { 0: String(a.count) }))
            .join(' · ');
    }, [group.steps, localize]);

    // Stable header label. Activity summary + "（用时 N 秒）" suffix when measurable;
    // the duration clause is dropped when nested (compact) OR when the measured span
    // is 0 (a single second-level frame would read a misleading "用时 0.0 秒").
    const label = useMemo<string>(() => {
        const seconds = formatSeconds(elapsedMs);
        const noDuration = compact || elapsedMs <= 0;
        // R3 完全拆平: a subagent segment reads "{goal} · {activity}" (falling back
        // to "子智能体 N" when the burst carried no per-agent goal), + 用时 suffix.
        if (subagent) {
            const core =
                [subagent.goal, activityText].filter(Boolean).join(' · ') ||
                localize('com_linsight_subagent_track', { 0: String(subagent.idx) });
            return noDuration ? core : localize('com_linsight_act_summary', { 0: core, 1: seconds });
        }
        // R1: activity-summary header (verbs + counts), the primary case.
        if (activityText) {
            return noDuration
                ? activityText
                : localize('com_linsight_act_summary', { 0: activityText, 1: seconds });
        }
        // Pure-reasoning fallback: the plain 深度思考 duration label.
        if (noDuration) {
            return localize(
                running
                    ? 'com_linsight_deep_thinking_running_compact'
                    : 'com_linsight_deep_thinking_done_compact',
            );
        }
        return localize(
            running ? 'com_linsight_deep_thinking_running' : 'com_linsight_deep_thinking_done',
            { 0: seconds },
        );
    }, [subagent, activityText, compact, elapsedMs, running, localize]);

    // R2 旁白 (degraded path, 2026-06): the segment's last reasoning sentence,
    // surfaced as a quiet aside so the collapsed stack reads like a colleague
    // reporting ("先摸清已有材料。"). Derived from the in-segment thinking — no
    // backend dependency. Suppressed in compact (drilldown) context; '' → hidden.
    const narration = useMemo(
        () => (compact ? '' : narrationFromSteps(group.steps, running)),
        [compact, group.steps, running],
    );

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
                icon={
                    // R3: a subagent segment carries the delegation icon so its work
                    // stays legible after the team shell is dissolved; a main-graph
                    // segment keeps the reasoning bulb.
                    subagent ? (
                        <Outlined.PeopleRound size={16} style={{ color: running ? ACCENT : MUTED }} />
                    ) : (
                        <Outlined.Bulb size={16} style={{ color: running ? ACCENT : MUTED }} />
                    )
                }
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
                {/* R2 旁白: shown only while collapsed — once expanded the full
                    thinking body carries the same reasoning, so the aside would just
                    duplicate it. Quiet (Muted), clamped to two lines. */}
                {!open && narration && (
                    <p className="mt-0.5 line-clamp-2 text-xs leading-5" style={{ color: MUTED }}>
                        {narration}
                    </p>
                )}
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

// Exported both as a named member (ExecutionTimeline) and as default, kept for
// back-compat with either import style.
export { DeepStepGroup };
export default DeepStepGroup;
