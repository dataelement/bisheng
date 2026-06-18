/**
 * SubagentTeamGroup — the delegation team shell (Wave2). Replaces SubagentRow.
 *
 * After backend B2, ONE main-graph `task` delegation point + the distinct
 * subgraph namespaces under it fold into ONE team group (agents.length = the
 * real number of subagents, e.g. 3 — not the old 22). The header reads
 * "Dispatched N subagents to research (M s)"; each agent is rendered as a
 * collapsible <SubagentTrack> so its real internal trail can be drilled into.
 *
 * Group-level collapse (per §5.4): default expanded via useState(true), NOT
 * bound to running — the shell stays stably open while children stream in
 * (inc-1 SubagentRow bound open to running and collapsed on completion, which
 * caused the whole group to snap shut on the last end frame).
 *
 * Parallel expression (§5.4): wide containers (>= 560px) lay the tracks out
 * side-by-side in equal-width flex columns (flex-1 min-w-0); narrow surfaces
 * (the TaskTurnPanel 80% bubble < 560px) degrade to a vertical stack. The
 * breakpoint is the container's own width (ResizeObserver), not the viewport —
 * the bubble can be narrow even on a wide screen.
 *
 * Token-for-token copy of the daily /c timeline tokens (no Chat/Messages import).
 */
import { Outlined } from 'bisheng-icons';
import { memo, useLayoutEffect, useRef, useState, type FC } from 'react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import SubagentTrack from './SubagentTrack';
import TimelineRail from './TimelineRail';
import { formatSeconds, useElapsedTicker } from './useElapsedTicker';
import type { MergedStep, SubagentAgent, SubagentGroup } from './stepUtils';

export interface SubagentTeamGroupProps {
    group: SubagentGroup;
}

/** Side-by-side breakpoint: at or above this container width (px) the tracks
 *  lay out in equal columns; below it they stack vertically. */
const SIDE_BY_SIDE_MIN = 560;

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

/** Observe the container width so the side-by-side ↔ stacked switch is driven by
 *  the group's own box, not the viewport (the bubble may be narrow on a wide
 *  screen). Returns a ref to attach and the latest measured width. */
function useContainerWidth(): [React.RefObject<HTMLDivElement>, number] {
    const ref = useRef<HTMLDivElement>(null);
    const [width, setWidth] = useState(0);
    useLayoutEffect(() => {
        const el = ref.current;
        if (!el) return;
        // Seed synchronously so the first paint already picks the right layout.
        setWidth(el.getBoundingClientRect().width);
        const ro = new ResizeObserver((entries) => {
            for (const entry of entries) setWidth(entry.contentRect.width);
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, []);
    return [ref, width];
}

export const SubagentTeamGroup: FC<SubagentTeamGroupProps> = memo(({ group }) => {
    const localize = useLocalize();
    // Group-level collapse: default expanded, NOT bound to running (§5.4).
    const [open, setOpen] = useState(true);

    const running = group.agents.some((a) => a.step.running || a.children.some((c) => c.running));
    const count = String(group.agents.length);

    const startMs = groupStartMs(group);
    const endMs = groupEndMs(group);
    const { elapsedMs } = useElapsedTicker(startMs, endMs, running);
    const seconds = formatSeconds(elapsedMs);

    const [containerRef, containerWidth] = useContainerWidth();
    // Before the first measurement (width === 0) default to side-by-side so a
    // wide layout doesn't flash a stacked column on mount.
    const sideBySide = containerWidth === 0 || containerWidth >= SIDE_BY_SIDE_MIN;

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
                        {/* Parallel layout: equal-width columns when wide, stacked
                            when the container is narrow. No connector between
                            columns (§5.4 "卡片间无连接线"). */}
                        <div
                            ref={containerRef}
                            className={cn('flex gap-x-4', sideBySide ? 'flex-row items-start' : 'flex-col')}
                        >
                            {group.agents.map((agent) => (
                                <div key={agent.step.callId} className={cn(sideBySide && 'min-w-0 flex-1')}>
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
