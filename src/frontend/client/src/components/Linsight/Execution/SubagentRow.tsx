/**
 * F035 Track H (P3) + 渲染优化增量一: subagent delegation team row.
 *
 * After backend B2, ONE main-graph `task` delegation point + the distinct
 * subgraph namespaces under it fold into ONE team group (agents.length = the
 * real number of subagents, e.g. 3 — not the old 22). Header reads "Dispatched
 * N subagents to research (M s)"; each card is one real subagent track.
 *
 * Counting fix (the "double error" root cause): a card's summary is now
 * "N tools · M thoughts" where N counts only non-thinking steps and M counts
 * thinking steps — the old "called N tools" actually counted thinking frames.
 * The count spans the agent's anchor step plus its children (the first step
 * seen under a namespace becomes `agent.step`, later same-ns steps are children).
 */
import { Outlined } from 'bisheng-icons';
import { Check, Recycle } from 'lucide-react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { StepRow } from './StepRow';
import type { MergedStep, SubagentAgent, SubagentGroup } from './stepUtils';

/** All steps belonging to one agent = its anchor step + later same-ns children. */
function agentSteps(agent: SubagentAgent): MergedStep[] {
    return [agent.step, ...agent.children];
}

/** Earliest startedAt → latest endedAt across all agents, in whole seconds.
 *  Returns 0 when no timestamps are available (the label tolerates 0). */
function groupElapsedSeconds(group: SubagentGroup): number {
    let min: number | undefined;
    let max: number | undefined;
    for (const agent of group.agents) {
        for (const step of agentSteps(agent)) {
            if (step.startedAt !== undefined) min = min === undefined ? step.startedAt : Math.min(min, step.startedAt);
            if (step.endedAt !== undefined) max = max === undefined ? step.endedAt : Math.max(max, step.endedAt);
        }
    }
    if (min === undefined || max === undefined) return 0;
    return Math.max(0, Math.round(max - min));
}

function SubagentCard({ agent }: { agent: SubagentAgent }) {
    const localize = useLocalize();
    const { step, children } = agent;
    const steps = agentSteps(agent);
    // Counting fix: tools = non-thinking steps, thoughts = thinking steps.
    const toolCount = steps.filter((s) => s.stepType !== 'thinking').length;
    const thinkingCount = steps.filter((s) => s.stepType === 'thinking').length;
    // Title: the delegation goal if known, else a 1-based "Subagent N" label.
    const goal = step.callReason || step.extraInfo?.delegate_goal;
    const title = goal || localize('com_linsight_subagent_track', { 0: String(agent.idx ?? 1) });
    // Running: surface the step currently in flight (or the latest one).
    const currentStep = [...steps].reverse().find((s) => s.running) || steps[steps.length - 1];
    const running = steps.some((s) => s.running);

    return (
        <div className="min-w-40 max-w-56 rounded-xl border border-gray-200 bg-white p-2.5 shadow-sm">
            <div className="flex items-center gap-1.5 text-xs font-medium text-gray-700">
                <Recycle size={12} className="shrink-0 text-blue-500" />
                <span className="truncate">{title}</span>
            </div>
            <div className="mt-1.5 flex items-center gap-1.5 text-xs text-gray-500">
                {running ? (
                    <>
                        <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-blue-500" />
                        <span className="truncate">{currentStep?.name || localize('com_linsight_subagent_running')}</span>
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
        </div>
    );
}

export function SubagentRow({ group }: { group: SubagentGroup }) {
    const localize = useLocalize();
    const running = group.agents.some((a) => a.step.running || a.children.some((c) => c.running));
    const count = String(group.agents.length);
    const seconds = String(groupElapsedSeconds(group));

    return (
        <StepRow
            icon={<Outlined.PeopleRound size={16} className={cn(running ? 'text-primary' : 'text-[#333]')} />}
            title={
                <span>
                    {localize(running ? 'com_linsight_subagent_team_running' : 'com_linsight_subagent_team_done', {
                        0: count,
                        1: seconds,
                    })}
                </span>
            }
            running={running}
        >
            <div className="flex flex-wrap gap-2 py-1">
                {group.agents.map((agent) => (
                    <SubagentCard key={agent.step.callId} agent={agent} />
                ))}
            </div>
        </StepRow>
    );
}
