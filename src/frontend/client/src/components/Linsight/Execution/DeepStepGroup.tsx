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
 * tokens come from execTokens; the live 用时 ticker is isolated in GroupHeaderLabel
 * so a 100ms tick re-renders only the header text, never the group body.
 */
import { Outlined } from 'bisheng-icons';
import { memo, useEffect, useMemo, useRef, useState, type FC, type ReactNode } from 'react';
import { useLocalize } from '~/hooks';
import { useCollapseState } from '~/store/linsightCollapse';
import { cn } from '~/utils';
import { ACCENT, ACTIVITY_I18N, BODY, INK } from './execTokens';

// Node-header palette, aligned with the blue-box IntentRow/StepRow: the static
// leading glyph takes Ink like the Clap icon, while the live loading spinner keeps
// the single Accent (blue) highlight; the chevron is muted and darkens on hover;
// the title + narration sit lighter as quiet meta.
const NODE_TEXT = '#999999';
import { GroupHeaderLabel } from './GroupHeaderLabel';
import { KnowledgeRow } from './KnowledgeRow';
import { NarrationTicker } from './NarrationTicker';
import ToolRowLite from './ToolRowLite';
import { mergedStepRenderEqual, narrationFromSteps, summarizeActivity } from './stepUtils';
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

const DeepStepGroupBase: FC<DeepStepGroupProps> = ({ group, compact = false, subagent, active = false }) => {
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
                    <GroupHeaderLabel
                        activityText={activityText}
                        subagent={subagent}
                        compact={compact}
                        startMs={startMs}
                        endMs={endMs}
                        running={running}
                    />
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

DeepStepGroupBase.displayName = 'DeepStepGroup';

/**
 * React.memo comparator. The WS pump rebuilds the WHOLE timeline node tree (fresh
 * MergedStep / group objects) on EVERY appended frame — including the many thinking
 * token-delta frames — so by default every历史 (frozen) episode re-renders dozens
 * of times a second during streaming. That starves the live 100ms elapsed ticker
 * and makes the "用时 N 秒" counter advance unevenly / skip seconds. A frozen
 * episode is semantically immutable, so skip its re-render when nothing it renders
 * changed; the active tail (new output / a new step / a step closing) always
 * compares unequal and re-renders. Cost is O(steps) — far below re-rendering the
 * thinking-text + tool-row subtree it guards. The per-step "did it change?" check
 * is mergedStepRenderEqual (shared with ToolRowLite so the two gates can't drift).
 */
export function deepStepGroupPropsEqual(prev: DeepStepGroupProps, next: DeepStepGroupProps): boolean {
    if (prev.active !== next.active || prev.compact !== next.compact) return false;
    if (prev.subagent?.idx !== next.subagent?.idx || prev.subagent?.goal !== next.subagent?.goal) return false;
    const a = prev.group;
    const b = next.group;
    if (a.running !== b.running || a.startedAt !== b.startedAt || a.endedAt !== b.endedAt) return false;
    if (a.steps.length !== b.steps.length) return false;
    for (let i = 0; i < a.steps.length; i++) {
        if (!mergedStepRenderEqual(a.steps[i], b.steps[i])) return false;
    }
    return true;
}

const DeepStepGroup = memo(DeepStepGroupBase, deepStepGroupPropsEqual);
DeepStepGroup.displayName = 'DeepStepGroup';

// Exported both as a named member (ExecutionTimeline) and as default, kept for
// back-compat with either import style.
export { DeepStepGroup };
export default DeepStepGroup;
