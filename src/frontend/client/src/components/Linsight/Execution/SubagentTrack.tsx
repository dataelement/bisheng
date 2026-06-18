/**
 * SubagentTrack — one delegated subagent rendered as a row inside the team
 * monitor panel (§2.3), with an in-place full-width drilldown on expand.
 *
 * Collapsed row: `[status] {title} ………………………………………… [chevron]`.
 *   - title: delegate_goal when present, else the localized "子智能体 N" label.
 *   - NO time / NO activity meta on the card — time is a top-level property (the
 *     team header carries the elapsed clause); repeating it per card + per nested
 *     thinking group piled up three layers of duration, so the card stays clean.
 *   - status: running → Accent Loading spin (the panel may light several at once);
 *     done → Muted CheckCircle.
 *
 * Expanded (drilldown, §2.3): the row grows a full-width white drilldown IN PLACE
 * via a grid 0fr→1fr, running buildTimelineGroups(agent.children) and rendering
 * the subagent's REAL internal deep-thinking groups with the SAME DeepStepGroup
 * styling as the top level (recursive isomorphism).
 *
 * Token-for-token copy of the daily /c timeline tokens (it does NOT import or
 * touch any Chat/Messages component — the shared primitives carry the tokens).
 */
import { Outlined } from 'bisheng-icons';
import { memo, useMemo, type FC } from 'react';
import { useLocalize } from '~/hooks';
import { useCollapseState } from '~/store/linsightCollapse';
import { cn } from '~/utils';
import DeepStepGroup from './DeepStepGroup';
import { INK, MUTED } from './execTokens';
import { useExecutionLive } from './executionLive';
import { KnowledgeRow } from './KnowledgeRow';
import { RunningSpinner } from './StepRow';
import ToolRowLite from './ToolRowLite';
import { buildTimelineGroups, type MergedStep, type SubagentAgent } from './stepUtils';

export interface SubagentTrackProps {
    agent: SubagentAgent;
}

/** All steps belonging to one agent = its anchor step + later same-ns children. */
function agentSteps(agent: SubagentAgent): MergedStep[] {
    return [agent.step, ...agent.children];
}

const SubagentTrack: FC<SubagentTrackProps> = memo(({ agent }) => {
    const localize = useLocalize();
    // L3 default-collapsed: a subagent's inner trail is the deepest tier, so it
    // stays folded until the user drills in. Persisted to sessionStorage keyed by
    // the subagent's namespace (its real identity); falls back to the anchor
    // callId when no namespace is present.
    const persistKey = agent.step.namespace || agent.step.callId || '';
    const [open, setOpen] = useCollapseState(persistKey, false);

    const steps = agentSteps(agent);
    // Gate on the turn being live (same dangling-end-frame guard as the team): a
    // completed turn freezes the card to done even if a step never closed.
    const live = useExecutionLive();
    const running = live && steps.some((s) => s.running);

    // Title (stable scheme): delegate_goal when present, else the "子智能体 N"
    // label. The narration-as-title experiment is reverted — a goal or a stable
    // index reads cleaner than a mixed-language reasoning sentence.
    const goal = agent.step.callReason || agent.step.extraInfo?.delegate_goal || '';
    const title = goal || localize('com_linsight_subagent_track', { 0: String(agent.idx ?? 1) });

    // Drilldown (§2.3): build the subagent's own timeline from its children only.
    // The input is pure thinking+tool (no delegation frame, no namespace flip), so
    // buildTimelineGroups collapses it into deep_step_groups / steps — the same
    // render primitives used at the top level (recursive isomorphism).
    const lastChild = agent.children[agent.children.length - 1];
    const sig = `${agent.children.length}:${running ? 1 : 0}:${lastChild?.callId ?? ''}`;
    const nodes = useMemo(() => buildTimelineGroups(agent.children), [sig]); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        // A panel row (the SubagentTeamGroup panel owns the border/ground/hairlines):
        // a header toggle button + an in-place full-width drilldown sibling.
        <div className="flex w-full min-w-0 flex-col" data-persist-key={persistKey}>
            {/* Header row = the clickable toggle: status icon + title + chevron
                (no time / meta). Enter/Space fire natively (it's a real button). */}
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left"
            >
                <span className="flex size-4 shrink-0 items-center justify-center">
                    {running ? (
                        <RunningSpinner />
                    ) : (
                        <Outlined.CheckCircle size={16} style={{ color: MUTED }} />
                    )}
                </span>
                <span
                    className="min-w-0 flex-1 truncate text-sm font-medium leading-[22px]"
                    style={{ color: INK }}
                >
                    {title}
                </span>
                <Outlined.Down
                    aria-hidden
                    size={16}
                    className={cn('shrink-0 transform-gpu transition-transform duration-200', open && 'rotate-180')}
                    style={{ color: MUTED }}
                />
            </button>
            {/* In-place full-width drilldown (sibling of the header button): a grid
                0fr→1fr grows the real internal trail downward on a clean white
                ground; max-h + scroll keeps one card from blowing past the viewport. */}
            <div
                className="grid w-full transition-all duration-300 ease-out"
                style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
            >
                <div className="min-h-0 overflow-hidden">
                    <div className="max-h-[60vh] w-full min-w-0 overflow-y-auto bg-white px-3 pb-3 pt-1">
                        <div className="flex flex-col gap-3">
                            {nodes.map((node, i) => {
                                if (node.kind === 'deep_step_group') {
                                    // compact: drop the per-group duration inside the drilldown
                                    // (time lives at the team-header level only).
                                    return (
                                        <DeepStepGroup
                                            key={node.steps[0]?.callId ?? `dsg-${i}`}
                                            group={node}
                                            compact
                                        />
                                    );
                                }
                                if (node.kind === 'subagent_group') {
                                    // Defensive: a subagent's own children never form a
                                    // nested team group (no delegation frame inside) —
                                    // skip rather than recurse infinitely.
                                    return null;
                                }
                                const { step } = node;
                                if (step.stepType === 'knowledge') return <KnowledgeRow key={step.callId} step={step} />;
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
