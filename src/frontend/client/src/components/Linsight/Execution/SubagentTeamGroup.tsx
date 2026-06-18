/**
 * SubagentTeamGroup — the delegation team monitor panel (§2.2). Replaces the old
 * "正在派出 N 子智能体（M 秒）" header with the spec narrative title.
 *
 * After backend B2, ONE main-graph `task` delegation point + the distinct
 * subgraph namespaces under it fold into ONE team group (agents.length = the
 * real number of subagents, e.g. 3 — not the old 22). Per §2.2 the header reads
 * "已派出 N 个子智能体并行调研" with a right-aligned tabular meta
 * "N 个子代理 · 用时 M秒"; each agent is rendered as a collapsible <SubagentTrack>.
 *
 * Monitor panel (§2.2): the agents sit in a `rounded-lg border #E8EAED` panel
 * grounded #FAFBFC, separated by 1px hairlines (not independent boxes).
 *
 * Group-level collapse (§2.1 fold contract): default = running (expanded while
 * live, collapsed once done), persisted to sessionStorage so a manual toggle
 * survives refresh / session switch. The shell never auto-toggles after a user
 * choice.
 *
 * Token-for-token copy of the daily /c timeline tokens (no Chat/Messages import).
 */
import { Outlined } from 'bisheng-icons';
import { memo, type FC } from 'react';
import { useLocalize } from '~/hooks';
import { useCollapseState } from '~/store/linsightCollapse';
import { cn } from '~/utils';
import { ACCENT, HAIRLINE, INK, MUTED, SURFACE } from './execTokens';
import { useExecutionLive } from './executionLive';
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

    // Gate on the turn being live: a completed/stopped turn means nothing is
    // running, so a safety-blocked subagent step that never got its end frame
    // can't keep "正在派出…（已用 N 秒）…" ticking after the task finished.
    const live = useExecutionLive();
    const running = live && group.agents.some((a) => a.step.running || a.children.some((c) => c.running));
    const count = group.agents.length;

    // Group-level collapse: persisted to sessionStorage keyed by the first agent's
    // callId; default = running. NOT auto-bound to running after a user toggle.
    const persistKey = group.agents[0]?.step.callId ?? '';
    const [open, setOpen] = useCollapseState(persistKey, running);

    const startMs = groupStartMs(group);
    const endMs = groupEndMs(group);
    const { elapsedMs } = useElapsedTicker(startMs, endMs, running);

    // Stable label scheme (reverted from the narration experiment): the original
    // "已派出 N 个子智能体调研（用时 M 秒）" key carries both the count and the
    // duration inline, so there is no separate right-side meta. The i18n key bakes
    // in "（用时 {{1}} 秒）" → feed the bare number (formatSeconds).
    const label = localize(
        running ? 'com_linsight_subagent_team_running' : 'com_linsight_subagent_team_done',
        { 0: String(count), 1: formatSeconds(elapsedMs) },
    );

    const handleToggle = (next: boolean) => setOpen(next);

    return (
        <div className="flex w-full min-w-0 gap-2 animate-thinking-appear">
            <TimelineRail
                icon={
                    <Outlined.PeopleRound
                        size={16}
                        style={{ color: running ? ACCENT : MUTED }}
                    />
                }
                showConnector={open}
            />
            <div className="flex min-w-0 flex-1 flex-col pb-3">
                <button
                    type="button"
                    onClick={() => handleToggle(!open)}
                    className={cn(
                        'group flex w-full items-center gap-2 text-sm font-medium leading-[22px]',
                        running && 'animate-pulse',
                    )}
                    style={{ color: INK }}
                >
                    <span className="min-w-0 truncate">{label}</span>
                    <Outlined.Down
                        size={16}
                        className={cn('shrink-0 transform-gpu transition-transform duration-200', open && 'rotate-180')}
                        style={{ color: MUTED }}
                    />
                </button>
                <div
                    className={cn('grid transition-all duration-300 ease-out', open && 'mt-2')}
                    style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
                >
                    <div className="min-h-0 overflow-hidden">
                        {/* Monitor panel (§2.2): one rounded-lg hairline-bordered
                            surface; each agent is a row separated from its
                            neighbour by a 1px hairline (no independent boxes). */}
                        <div
                            className="overflow-hidden rounded-lg"
                            style={{ border: `1px solid ${HAIRLINE}`, background: SURFACE }}
                        >
                            {group.agents.map((agent, i) => (
                                <div
                                    key={agent.step.callId}
                                    style={i > 0 ? { borderTop: `1px solid ${HAIRLINE}` } : undefined}
                                >
                                    <SubagentTrack agent={agent} />
                                </div>
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
