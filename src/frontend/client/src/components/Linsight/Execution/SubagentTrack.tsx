/**
 * SubagentTrack — one delegated subagent rendered as a collapsible timeline
 * track (Wave2). Replaces the inc-1 SubagentCard's heterogeneous lucide
 * Recycle/blue/green card with the shared timeline language.
 *
 * Header  : the delegation goal (callReason / extra_info.delegate_goal) or a
 *           localized "Subagent N" fallback; trailing summary "N tools · M
 *           thoughts" (N = non-thinking steps, M = thinking steps — the same
 *           counting口径 as inc-1 agentSteps). Running shows the current
 *           activity instead of the summary.
 * Drilldown (the Wave2 key capability): expanding the track runs
 *           buildTimelineGroups over [agent.step, ...agent.children] and renders
 *           the subagent's REAL internal research trail — a DeepStepGroup for
 *           consecutive thinking+tool runs, plus ToolRowLite for any stray step.
 *           inc-1 cards could not reveal a subagent's inner steps; this does.
 *
 * Token-for-token copy of the daily /c timeline tokens (it does NOT import or
 * touch any Chat/Messages component — the shared primitives carry the tokens).
 */
import { Outlined } from 'bisheng-icons';
import { memo, useMemo, type FC } from 'react';
import { useLocalize } from '~/hooks';
import { useCollapseState } from '~/store/linsightCollapse';
import CollapsibleTimelineItem from './CollapsibleTimelineItem';
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
    // L3 default-collapsed (F7): a subagent's inner trail is the deepest tier,
    // so it stays folded until the user drills in. Persisted to sessionStorage
    // keyed by the subagent's namespace (its real identity) so a manual expand
    // survives refresh / session switch; falls back to the anchor callId when no
    // namespace is present.
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
        <CollapsibleTimelineItem
            icon={
                running ? (
                    <RunningSpinner />
                ) : (
                    <Outlined.PeopleRound size={16} className="text-[#C9CDD4]" />
                )
            }
            label={title}
            summary={
                running
                    ? `· ${currentActivity}`
                    : `· ${localize('com_linsight_subagent_summary', {
                          0: String(toolCount),
                          1: String(thinkingCount),
                      })}`
            }
            streaming={running}
            open={open}
            onToggle={setOpen}
            persistKey={persistKey}
        >
            {/* Subagent's real internal research trail (the Wave2 drilldown). */}
            <div className="flex flex-col gap-3">
                {nodes.map((node, i) => {
                    if (node.kind === 'deep_step_group') {
                        return <DeepStepGroup key={node.steps[0]?.callId ?? `dsg-${i}`} group={node} />;
                    }
                    if (node.kind === 'subagent_group') {
                        // Defensive: a subagent's own children never form a nested
                        // team group (no delegation frame inside), so this branch
                        // shouldn't fire — skip rather than recurse infinitely.
                        return null;
                    }
                    const { step } = node;
                    if (step.stepType === 'knowledge') return <KnowledgeRow key={step.callId} step={step} />;
                    return <ToolRowLite key={step.callId} step={step} />;
                })}
            </div>
        </CollapsibleTimelineItem>
    );
});

SubagentTrack.displayName = 'SubagentTrack';

export default SubagentTrack;
