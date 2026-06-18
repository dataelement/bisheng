/**
 * SubagentTeamGroup — the delegation team shell (Wave2). Replaces SubagentRow.
 *
 * After backend B2, ONE main-graph `task` delegation point + the distinct
 * subgraph namespaces under it fold into ONE team group (agents.length = the
 * real number of subagents, e.g. 3 — not the old 22). The header reads
 * "Dispatched N subagents to research (M s)"; each agent is rendered as a
 * collapsible <SubagentTrack> so its real internal trail can be drilled into.
 *
 * Group-level collapse (per §5.4 / F7): default = running (expanded while live,
 * collapsed once done to a summary line), persisted to sessionStorage so a
 * manual toggle survives refresh / session switch. The shell never auto-toggles
 * after a user choice (inc-1 SubagentRow bound open to running and collapsed on
 * completion, which caused the whole group to snap shut on the last end frame).
 *
 * Parallel expression (§5.4): the tracks lay out in a CSS grid with
 * `auto-fill, minmax(180px, 1fr)` — wide containers fit 3-4 cards per row (the
 * parallel signal), narrow surfaces (the TaskTurnPanel 80% bubble) reflow to a
 * single column. Pure CSS, no JS measurement, no first-paint stacked flash.
 * Expanding a card lets it span the full row (gridColumn '1 / -1', set inside
 * SubagentTrack) so its drilldown reads at full content width.
 *
 * Token-for-token copy of the daily /c timeline tokens (no Chat/Messages import).
 */
import { Outlined } from 'bisheng-icons';
import { memo, type FC } from 'react';
import { useLocalize } from '~/hooks';
import { useCollapseState } from '~/store/linsightCollapse';
import { cn } from '~/utils';
import SubagentTrack from './SubagentTrack';
import TimelineRail from './TimelineRail';
import { formatSeconds, useElapsedTicker } from './useElapsedTicker';
import type { MergedStep, SubagentAgent, SubagentGroup } from './stepUtils';

export interface SubagentTeamGroupProps {
    group: SubagentGroup;
}

/** All steps belonging to one agent = its anchor step + later same-ns children. */
function agentSteps(agent: SubagentAgent): MergedStep[] {
    return [agent.step, ...agent.children];
}

/** Earliest startedAt across all agents' steps, in ms (sec-level ts * 1000).
 *  undefined when no timestamps are present (caller hides the 用时 clause). */
function groupStartMs(group: SubagentGroup): number | undefined {
    let min: number | undefined;
    for (const agent of group.agents) {
        for (const step of agentSteps(agent)) {
            if (step.startedAt !== undefined) min = min === undefined ? step.startedAt : Math.min(min, step.startedAt);
        }
    }
    return min === undefined ? undefined : min * 1000;
}

/** Latest endedAt across all agents' steps, in ms (sec-level ts * 1000). */
function groupEndMs(group: SubagentGroup): number | undefined {
    let max: number | undefined;
    for (const agent of group.agents) {
        for (const step of agentSteps(agent)) {
            if (step.endedAt !== undefined) max = max === undefined ? step.endedAt : Math.max(max, step.endedAt);
        }
    }
    return max === undefined ? undefined : max * 1000;
}

export const SubagentTeamGroup: FC<SubagentTeamGroupProps> = memo(({ group }) => {
    const localize = useLocalize();

    const running = group.agents.some((a) => a.step.running || a.children.some((c) => c.running));
    const count = String(group.agents.length);

    // Group-level collapse (F7): persisted to sessionStorage keyed by the first
    // agent's callId; default = running (expanded while live to watch the team,
    // collapsed once done to the "已派出 N 个子智能体（用时 M 秒）" summary line).
    // NOT auto-bound to running after a user toggle — the shell never snaps shut
    // on the last end frame.
    const persistKey = group.agents[0]?.step.callId ?? '';
    const [open, setOpen] = useCollapseState(persistKey, running);

    const startMs = groupStartMs(group);
    const endMs = groupEndMs(group);
    const { elapsedMs } = useElapsedTicker(startMs, endMs, running);
    const seconds = formatSeconds(elapsedMs);

    const handleToggle = (next: boolean) => setOpen(next);

    return (
        // Reuse the timeline rail anatomy directly (not CollapsibleTimelineItem)
        // because the group HEADER style differs from a track trigger: the team
        // header is the bolder #212121 group title, while a track trigger is the
        // muted #999999 node title.
        <div className="flex w-full min-w-0 gap-1.5 animate-thinking-appear">
            <TimelineRail
                icon={<Outlined.PeopleRound size={16} className={cn(running ? 'text-primary' : 'text-[#C9CDD4]')} />}
                showConnector={open}
            />
            <div className="flex min-w-0 flex-1 flex-col pb-3">
                <button
                    type="button"
                    onClick={() => handleToggle(!open)}
                    className={cn(
                        'group flex w-fit max-w-full items-center gap-1 text-sm font-medium leading-[22px] text-[#212121]',
                        running && 'animate-pulse',
                    )}
                >
                    <span className="min-w-0 truncate">
                        {localize(running ? 'com_linsight_subagent_team_running' : 'com_linsight_subagent_team_done', {
                            0: count,
                            1: seconds,
                        })}
                    </span>
                    <Outlined.Down
                        size={16}
                        className={cn(
                            'shrink-0 transform-gpu text-[#999999] transition-transform duration-200',
                            open && 'rotate-180',
                        )}
                    />
                </button>
                <div
                    className={cn('grid transition-all duration-300 ease-out', open && 'mt-2')}
                    style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
                >
                    <div className="min-h-0 overflow-hidden">
                        {/* Parallel layout: a CSS grid auto-fill of minmax(180px,
                            1fr) cards (no JS measurement). Wide → 3-4 cards/row;
                            narrow bubble → single column. Each SubagentTrack is the
                            grid item; an expanded one spans the full row via its own
                            gridColumn '1 / -1'. No connector between cards (§5.4
                            "卡片间无连接线"). */}
                        <div
                            className="grid gap-2.5"
                            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))' }}
                        >
                            {group.agents.map((agent) => (
                                <SubagentTrack key={agent.step.callId} agent={agent} />
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
});

SubagentTeamGroup.displayName = 'SubagentTeamGroup';

export default SubagentTeamGroup;
