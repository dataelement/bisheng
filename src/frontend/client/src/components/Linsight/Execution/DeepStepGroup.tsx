/**
 * DeepStepGroup — task-mode "deep thinking" group, isomorphic to the daily /c
 * DeepThinkingGroup. It aggregates one episode of consecutive top-level steps
 * (thinking + tool + knowledge) into a single collapsible group whose header
 * reads "正在深度思考（已用 N 秒）..." while live, or "已深度思考（用时 N 秒）"
 * once closed.
 *
 * Stable-label scheme (reverted from the narration experiment): the header is the
 * plain duration label — predictable and quiet — fronted by a consistent rail
 * icon so EVERY timeline node carries one. The rail + icon + gap give every
 * top-level node one consistent left spine — main-graph segments and exploded
 * per-subagent segments alike (no more ragged left edge).
 *
 * Icon color regime (§1.3): running → Accent (the single live highlight) + the
 * header pulses; done → Muted. The old invisible #C9CDD4 grey is gone.
 *
 * Single-level fold: the expanded body lays out the thinking passages directly as
 * Body-colored text (no inner "思考内容" collapsible) interleaved with tool /
 * knowledge rows in original timeline order. The group shell owns the only
 * open/close state, persisted via useCollapseState. The default fold tracks the
 * `active` prop (the live tail episode → open; superseded / done → collapsed) —
 * deliberately NOT the per-tool group.running, which toggles on every tool call
 * and used to make the whole group flicker open/closed mid-episode.
 *
 * It does NOT import or modify any Chat/Messages (daily /c) component — all
 * tokens come from execTokens, the timer math from useElapsedTicker.
 */
import { Outlined } from 'bisheng-icons';
import { useEffect, useMemo, useRef, useState, type FC, type ReactNode } from 'react';
import { useLocalize } from '~/hooks';
import { useCollapseState } from '~/store/linsightCollapse';
import { cn, formatSeconds } from '~/utils';
import { ACCENT, ACTIVITY_I18N, BODY, INK } from './execTokens';

// Node-header palette, aligned with the blue-box IntentRow/StepRow: the static
// leading glyph takes Ink like the Clap icon, while the live loading spinner keeps
// the single Accent (blue) highlight; the chevron is muted and darkens on hover;
// the title + narration sit lighter as quiet meta.
const NODE_TEXT = '#999999';
import { KnowledgeRow } from './KnowledgeRow';
import { NarrationTicker } from './NarrationTicker';
import ToolRowLite from './ToolRowLite';
import { useElapsedTicker } from './useElapsedTicker';
import { firstLine, narrationFromSteps, summarizeActivity } from './stepUtils';
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
    /**
     * Whether this group is the ACTIVE (live tail) episode of a running container.
     * It is the single source of truth for every live-vs-done UI facet — the
     * open/collapse default, the 正在/已 label, the header pulse, the accent color,
     * the elapsed ticker, and the narration mode.
     *
     * It deliberately REPLACES the old `group.running && live` driver. `group.running`
     * is "any step in this episode currently mid-flight", which toggles true↔false
     * MANY times within one live episode: thinking frames ship as `status:'end'`
     * (never running), and a tool step is running only between its start and end
     * frames — so binding the fold to it made the whole group expand on every tool
     * call and collapse again the instant it finished ("上下反复跳跃"). `active` is
     * stable for the episode's whole lifetime: the parent (ExecutionTimeline) sets
     * it true for the last node while the container is live, so the group stays
     * steadily expanded and collapses exactly once when a newer episode supersedes
     * it. Default false ⇒ a done / historical group (collapsed summary, frozen clock).
     */
    active?: boolean;
}

/**
 * Subagent header budget: the delegation goal is the `task` tool's `description`
 * arg, which the model writes as a long multi-sentence instruction. The header
 * renders only its first sentence/clause (firstLine), widened to ~one line's worth
 * so a typical goal stays intact instead of being chopped mid-word by `truncate`.
 */
const SUBAGENT_GOAL_TITLE_MAX = 48;

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

const DeepStepGroup: FC<DeepStepGroupProps> = ({ group, compact = false, subagent, active = false }) => {
    const localize = useLocalize();
    // `active` (the live tail episode) — NOT the volatile per-tool group.running —
    // is the live-vs-done signal for the entire group. Binding everything to active
    // keeps the fold/label/clock stable for the episode's whole lifetime instead of
    // flickering open/closed on each tool call (see the `active` prop doc). A
    // completed / stopped / historical container passes active=false, so a dangling
    // step that never got its end frame can no longer keep the group ticking
    // "正在深度思考…".
    const running = active;
    // Group-level fold: ONE stable open state per group, persisted to
    // sessionStorage so a manual toggle survives refresh / session switch.
    // Default = collapsed for every group (live or done): even the live tail
    // episode starts folded to its single summary + narration line, so task mode
    // opens quiet instead of dumping the full reasoning. The user expands a group
    // manually to read the full thinking; the collapsed header still streams the
    // latest thought via the NarrationTicker below.
    const persistKey = group.steps[0]?.callId ?? '';
    const [open, setOpen] = useCollapseState(persistKey, false);

    // Sticky-header pin detection. A zero-height sentinel sits just above the
    // header; once it scrolls past the TOP edge of the chat scroll container, the
    // header is pinned. We then paint a white ::before cap over the container's top
    // padding strip — overflow clips at the padding box, so scrolled body text
    // would otherwise bleed into that strip above the pinned header. Only active
    // while expanded (a collapsed header has no body to flank).
    const sentinelRef = useRef<HTMLDivElement | null>(null);
    const [pinned, setPinned] = useState(false);
    useEffect(() => {
        const el = sentinelRef.current;
        if (!open || !el) {
            setPinned(false);
            return;
        }
        const root = el.closest('.overflow-y-auto') as HTMLElement | null;
        const io = new IntersectionObserver(
            ([entry]) => {
                const rootTop = entry.rootBounds?.top ?? 0;
                // Pinned only when the sentinel left past the TOP edge (leaving past
                // the bottom just means the whole node scrolled out of view).
                setPinned(!entry.isIntersecting && entry.boundingClientRect.top <= rootTop);
            },
            { root, threshold: [0, 1] },
        );
        io.observe(el);
        return () => io.disconnect();
    }, [open]);

    // Timestamps on MergedStep are second-level ints (BaseEvent.timestamp); the
    // ticker math is in milliseconds, so scale up here.
    const startMs = group.startedAt != null ? group.startedAt * 1000 : null;
    const endMs = group.endedAt != null ? group.endedAt * 1000 : null;
    const { elapsedMs } = useElapsedTicker(startMs, endMs, running);

    // R1 (段流重构 2026-06): the segment header is the ACTIVITY SUMMARY of what
    // this episode did ("检索知识库 3 次 · 读 2 文件") — built from summarizeActivity,
    // which excludes thinking / write_todos / ls / ask_user. A pure-reasoning
    // segment yields no activity and falls back to the plain 深度思考 label.
    const activity = useMemo(() => summarizeActivity(group.steps), [group.steps]);
    const activityText = useMemo<string>(() => {
        if (!activity.length) return '';
        return activity
            .map((a) => localize(ACTIVITY_I18N[a.category], { 0: String(a.count) }))
            .join(' · ');
    }, [activity, localize]);
    // A file-editing episode (dominant activity is write_file) carries the write
    // glyph instead of the generic reasoning bulb.
    const isWriteFile = activity[0]?.category === 'write_file';

    // Stable header label. Activity summary + "（用时 N 秒）" suffix when measurable;
    // the duration clause is dropped when nested (compact) OR when the measured span
    // is 0 (a single second-level frame would read a misleading "用时 0.0 秒").
    const label = useMemo<string>(() => {
        const seconds = formatSeconds(elapsedMs);
        const noDuration = compact || elapsedMs <= 0;
        // R3 完全拆平: a subagent segment is headed by its delegation GOAL + 用时.
        if (subagent) {
            // The goal is the subagent's identity, so it OWNS the header line. Show
            // only its GIST — the first sentence/clause, hard-capped to ~one line via
            // firstLine — so a long multi-sentence instruction doesn't read as a
            // run-on chopped mid-word by `truncate`.
            //
            // The activity summary (联网搜索 N 次 · 编辑 M 文件) is intentionally NOT
            // appended here: it is process detail that competes with the goal for
            // width (and collides with a truncated goal's open paren), and it is
            // already visible when the card is expanded. It is kept only as a
            // FALLBACK label for a goal-less (degraded) subagent — there it is more
            // informative than a bare "子智能体 N".
            const goalGist = firstLine(subagent.goal, SUBAGENT_GOAL_TITLE_MAX);
            const core =
                goalGist || activityText || localize('com_linsight_subagent_track', { 0: String(subagent.idx) });
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

    // Single-column layout so the header (icon + title) pins as ONE row. The body
    // and narration are indented (pl-6 = 16px icon + 8px gap) to stay aligned under
    // the title, matching the old rail + content two-column offset.
    return (
        <div className="w-full min-w-0 pb-3 animate-thinking-appear">
            {/* Zero-height sentinel driving the IntersectionObserver pin detection. */}
            <div ref={sentinelRef} aria-hidden className="h-0" />
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className={cn(
                    // 4px vertical padding always, so the header height is identical
                    // collapsed and expanded (no jump on toggle).
                    'group flex w-full items-center gap-2 py-1 text-left text-sm font-medium leading-[22px]',
                    // When expanded, pin the whole header row to the top of the chat
                    // scroll area; the opaque white backing masks the body scrolling
                    // beneath it.
                    open && 'sticky top-0 z-20 bg-white',
                    // Once actually pinned, a solid white ::before cap covers the
                    // scroll container's top padding strip — body text would otherwise
                    // bleed above the header. (The body edge below the header is a hard
                    // cut; no soft gradient there.)
                    pinned &&
                        'before:absolute before:inset-x-0 before:bottom-full before:h-4 before:bg-white before:content-[""]',
                )}
                style={{ color: NODE_TEXT }}
            >
                {/* Icon regime: while running AND collapsed the node shows the
                    loading spinner; otherwise (expanded, or finished) a glyph —
                    subagent → delegation, file-editing episode → write, everything
                    else → reasoning bulb. All glyphs share NODE_ICON (unified ink);
                    the running pulse lives on the label so it never fades the backing. */}
                <span className="flex size-4 shrink-0 items-center justify-center">
                    {running && !open ? (
                        <Outlined.Loading size={16} className="animate-spin" style={{ color: ACCENT }} />
                    ) : subagent ? (
                        <Outlined.PeopleRound size={16} style={{ color: INK }} />
                    ) : isWriteFile ? (
                        <Outlined.Write size={16} style={{ color: INK }} />
                    ) : (
                        <Outlined.Bulb size={16} style={{ color: INK }} />
                    )}
                </span>
                {/* Title darkens to ink on hover (matching the StepRow blue-box
                    trigger). When expanded it stays a solid dark gray (the open node
                    is the focused one). While running the label breathes
                    (animate-pulse); hover halts the breathing so it settles to a solid
                    dark gray instead of fading in and out. */}
                <span
                    className={cn(
                        'min-w-0 truncate transition-colors group-hover:text-[#212121]',
                        open && 'text-[#212121]',
                        running && 'animate-pulse group-hover:animate-none',
                    )}
                >
                    {label}
                </span>
                {/* Single chevron rotates right→down (collapsed → expanded), matching
                    the StepRow / daily "深度思考" toggle; muted, darkening on hover. */}
                <Outlined.Down
                    size={16}
                    className={cn(
                        'shrink-0 transform-gpu text-[#8C8C8C] transition duration-200 group-hover:text-[#212121]',
                        !open && '-rotate-90',
                    )}
                />
            </button>
            {/* R2 旁白 (live thought ticker): the segment's latest COMPLETE sentence,
                advancing one sentence at a time with a vertical crossfade. Shown
                while the segment runs AND when collapsed; hidden only when a finished
                segment is expanded, where the full thinking body carries the same
                reasoning. Indented to align under the title. */}
            {(running || !open) && (
                <div className="pl-6">
                    <NarrationTicker text={narration} />
                </div>
            )}
            <div
                className={cn('grid transition-all duration-300 ease-out', open && 'mt-2')}
                style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
            >
                <div className="min-h-0 overflow-hidden">
                    <div className="flex flex-col gap-1.5 pl-6">{body}</div>
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
