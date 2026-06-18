/**
 * SubagentTrack — one delegated subagent rendered as a two-phase card:
 *   - collapsed (open=false): a polished card inside the team grid (dot texture +
 *     running sheen + circular white badge + title + status line), borrowing the
 *     colleague SubagentRow (3ceecea64) card visuals;
 *   - expanded (open=true): the card spans the full content column
 *     (gridColumn '1 / -1') and grows a full-width drilldown IN PLACE via a
 *     card-internal grid 0fr→1fr — fixing the "drilldown squeezed into a ~240px
 *     column, text 4-6 chars per line" complaint.
 *
 * Why not CollapsibleTimelineItem: that primitive is a rail + plain-text trigger;
 * the polished card is a different shape. The controlled open/onToggle/persistKey
 * contract here is IDENTICAL to CollapsibleTimelineItem (no new mode introduced).
 *
 * Drilldown (preserved Wave2 capability): expanding runs buildTimelineGroups over
 * [agent.step, ...agent.children] and renders the subagent's REAL internal trail
 * — DeepStepGroup for consecutive thinking+tool runs, KnowledgeRow / ToolRowLite
 * for stray steps — now FULL WIDTH (= content-column width = same as the
 * top-level DeepStepGroup), so a thinking passage wraps dozens of chars per line.
 *
 * Token-for-token copy of the daily /c timeline tokens (it does NOT import or
 * touch any Chat/Messages component — the shared primitives carry the tokens).
 */
import { Outlined } from 'bisheng-icons';
import { Check } from 'lucide-react';
import { memo, useMemo, type FC } from 'react';
import { useLocalize } from '~/hooks';
import { useCollapseState } from '~/store/linsightCollapse';
import { cn } from '~/utils';
import { DOT_BG, SHEEN } from './cardTexture';
import DeepStepGroup from './DeepStepGroup';
import { KnowledgeRow } from './KnowledgeRow';
import { RunningSpinner } from './StepRow';
import ToolRowLite from './ToolRowLite';
import { buildTimelineGroups, firstLine, type MergedStep, type SubagentAgent } from './stepUtils';

export interface SubagentTrackProps {
    agent: SubagentAgent;
}

/** All steps belonging to one agent = its anchor step + later same-ns children
 *  (sticks to the inc-1 SubagentRow counting口径). */
function agentSteps(agent: SubagentAgent): MergedStep[] {
    return [agent.step, ...agent.children];
}

const SubagentTrack: FC<SubagentTrackProps> = memo(({ agent }) => {
    const localize = useLocalize();
    // L3 default-collapsed (F7): a subagent's inner trail is the deepest tier, so
    // it stays folded until the user drills in. Persisted to sessionStorage keyed
    // by the subagent's namespace (its real identity) so a manual expand survives
    // refresh / session switch; falls back to the anchor callId when no namespace.
    const persistKey = agent.step.namespace || agent.step.callId || '';
    const [open, setOpen] = useCollapseState(persistKey, false);

    const steps = agentSteps(agent);
    // Counting fix carried from inc-1: tools = non-thinking steps, thoughts =
    // thinking steps. Spans the anchor step + its later same-ns children.
    const toolCount = steps.filter((s) => s.stepType !== 'thinking').length;
    const thinkingCount = steps.filter((s) => s.stepType === 'thinking').length;

    // Title: the delegation goal if known, else a 1-based "Subagent N" label.
    const goal = agent.step.callReason || agent.step.extraInfo?.delegate_goal;
    const title = goal || localize('com_linsight_subagent_track', { 0: String(agent.idx ?? 1) });

    const running = steps.some((s) => s.running);
    // Running: surface the step currently in flight (or the latest one) so the
    // collapsed header still carries live, real activity.
    const currentStep = [...steps].reverse().find((s) => s.running) || steps[steps.length - 1];
    const currentActivity =
        firstLine(currentStep?.output) || currentStep?.name || localize('com_linsight_subagent_running');

    // Drilldown: build the subagent's own timeline from its real steps. The input
    // is pure thinking+tool (no delegation frame, no namespace flip), so
    // buildTimelineGroups collapses it entirely into deep_step_groups / steps —
    // the same render primitives used at the top level (recursive isomorphism).
    const sig = `${steps.length}:${currentStep?.running ? 1 : 0}:${currentStep?.callId ?? ''}`;
    const nodes = useMemo(() => buildTimelineGroups(steps), [sig]); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        // The card shell IS the grid item. When expanded it spans the whole content
        // column (gridColumn '1 / -1') so its drilldown gets full readable width;
        // collapsed it stays a single auto column inside the team's auto-fill grid.
        // The shell is a plain div (NOT a button): the drilldown body contains its
        // own interactive buttons (DeepStepGroup / ToolRowLite), and nesting a
        // <button> inside a <button> is invalid HTML that the browser flattens.
        // The clickable toggle is the card HEADER button; the drilldown is its
        // sibling inside the shell.
        <div
            className={cn(
                'relative flex flex-col overflow-hidden rounded-lg border-[0.5px] border-[#ECECEC]',
                'shadow-[0px_4px_6px_0px_rgba(167,186,224,0.05)] transition-all',
                // expanded emphasis: border → faint blue, shadow slightly stronger
                // (same hue family as the dot texture, restrained).
                open && 'border-[#D6DEFF] shadow-[0px_6px_12px_0px_rgba(167,186,224,0.12)]',
            )}
            style={{ ...DOT_BG, gridColumn: open ? '1 / -1' : undefined }}
            data-persist-key={persistKey}
        >
            {/* Diagonal glint sweeping above the dots; the static mask fades the
                streak near the L/R edges so the overflow-hidden clip lands in an
                already-transparent zone. Only while the agent runs. */}
            {running && (
                <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0"
                    style={{
                        WebkitMaskImage:
                            'linear-gradient(to right, transparent 0%, #000 18%, #000 82%, transparent 100%)',
                        maskImage: 'linear-gradient(to right, transparent 0%, #000 18%, #000 82%, transparent 100%)',
                    }}
                >
                    <div className="absolute inset-0 animate-sheen-sweep" style={{ backgroundImage: SHEEN }} />
                </div>
            )}
            {/* Card header = the clickable toggle (badge + title + chevron + status
                line). Enter/Space fire it natively (it's a real button). */}
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="relative flex w-full flex-col items-start gap-1 px-4 py-2 text-left"
            >
                {/* Header row: circular white badge + title + chevron. */}
                <div className="flex w-full items-center gap-2">
                    <span className="flex shrink-0 items-center rounded-full bg-white p-[5px]">
                        {running ? (
                            <RunningSpinner />
                        ) : (
                            <Outlined.PeopleRound size={14} className="text-[#C9CDD4]" />
                        )}
                    </span>
                    {/* collapsed cards may wrap the goal to two lines; the expanded
                        full-width banner keeps a single truncated line. */}
                    <span
                        className={cn(
                            'min-w-0 flex-1 text-xs leading-5 text-[#1D2129]',
                            open ? 'truncate' : 'line-clamp-2',
                        )}
                    >
                        {title}
                    </span>
                    <Outlined.Down
                        aria-hidden
                        size={16}
                        className={cn(
                            'shrink-0 transform-gpu text-[#999] transition-transform duration-200',
                            open && 'rotate-180',
                        )}
                    />
                </div>
                {/* Status line: running = pulse dot + current activity; done =
                    green check + "N tools · M thoughts" summary. */}
                <div className="flex w-full items-center gap-2 text-xs leading-5 text-[#999]">
                    {running ? (
                        <>
                            <span className="size-2 shrink-0 animate-pulse rounded-full bg-[#212121]" />
                            <span className="truncate">{currentActivity}</span>
                        </>
                    ) : (
                        <>
                            <Check size={12} className="shrink-0 text-green-500" />
                            <span className="truncate">
                                {localize('com_linsight_subagent_summary', {
                                    0: String(toolCount),
                                    1: String(thinkingCount),
                                })}
                            </span>
                        </>
                    )}
                </div>
            </button>
            {/* In-place full-width drilldown (sibling of the header button, NOT
                nested in it): card-internal grid 0fr→1fr grows the real internal
                trail downward (same smooth animation as CollapsibleTimelineItem).
                White bg covers the dots so the DeepStepGroup text reads on a clean
                ground; max-h + scroll keeps a single card from blowing past the
                viewport. */}
            <div
                className="relative grid w-full transition-all duration-300 ease-out"
                style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
            >
                <div className="min-h-0 overflow-hidden">
                    <div className="max-h-[60vh] w-full min-w-0 overflow-y-auto bg-white px-4 pb-2 pl-3">
                        <div className="flex flex-col gap-3">
                            {nodes.map((node, i) => {
                                if (node.kind === 'deep_step_group') {
                                    return (
                                        <DeepStepGroup key={node.steps[0]?.callId ?? `dsg-${i}`} group={node} />
                                    );
                                }
                                if (node.kind === 'subagent_group') {
                                    // Defensive: a subagent's own children never form
                                    // a nested team group (no delegation frame inside)
                                    // — skip rather than recurse infinitely.
                                    return null;
                                }
                                const { step } = node;
                                if (step.stepType === 'knowledge')
                                    return <KnowledgeRow key={step.callId} step={step} />;
                                return <ToolRowLite key={step.callId} step={step} />;
                            })}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
});

SubagentTrack.displayName = 'SubagentTrack';

export default SubagentTrack;
