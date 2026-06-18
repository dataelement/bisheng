/**
 * ExecutionTimeline — the single aggregation entry for task-mode execution flow
 * (Wave2 / F5). Replaces StepList's bare dispatch: it walks
 * buildTimelineGroups(mergeStepFrames(history)) and renders the Wave2 timeline
 * node family (deep_step_group / subagent_group), isomorphic to the daily /c
 * "深度思考" surface. All four carrier surfaces (ExecutionFlow / TaskTurnPanel /
 * ConversationRound / TaskStepRow) collapse onto this one component so the
 * live-vs-refresh / per-task / session-scoped views can never drift.
 *
 * It does NOT import or touch any Chat/Messages (daily /c) component — the shared
 * visual tokens live in the task-mode primitives (CollapsibleTimelineItem /
 * TimelineRail / useElapsedTicker) and the Wave2 group components below.
 */
import { useMemo } from 'react';
import { DeepStepGroup } from './DeepStepGroup';
import { KnowledgeRow } from './KnowledgeRow';
import { SubagentTeamGroup } from './SubagentTeamGroup';
import { ToolRowLite } from './ToolRowLite';
import type { ExecStepEventData } from './stepUtils';
import { buildTimelineGroups, mergeStepFrames } from './stepUtils';

interface ExecutionTimelineProps {
    history: ExecStepEventData[] | null | undefined;
}

export function ExecutionTimeline({ history }: ExecutionTimelineProps) {
    // F3 perf: building the node tree is several O(n) passes (merge + group +
    // episode aggregation). The WS pump mutates `history` in place (same array
    // reference), so the reference alone is not enough to invalidate the memo — a
    // composite signature (length + last frame's status / call_id) re-fires it on
    // each appended/closed frame while skipping the wasteful per-render rebuild.
    const frames = history || [];
    const last = frames[frames.length - 1];
    const sig = `${frames.length}:${last?.status ?? ''}:${last?.call_id ?? ''}`;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional composite key over the in-place-mutated history array
    const nodes = useMemo(() => buildTimelineGroups(mergeStepFrames(history)), [sig]);
    if (!nodes.length) return null;

    return (
        // Group spacing aligns with the daily /c stack (gap-3 between groups).
        <div className="flex flex-col gap-3">
            {nodes.map((node, idx) => {
                if (node.kind === 'deep_step_group') {
                    // Stable key: first step's callId; fall back to index when an
                    // episode somehow has no steps (defensive — flush() never emits
                    // an empty episode, so this is a belt-and-braces guard).
                    const key = node.steps[0]?.callId ?? `deep_${idx}`;
                    return <DeepStepGroup key={key} group={node} />;
                }
                if (node.kind === 'subagent_group') {
                    // buildFlowNodes materializes a group only once a real subagent
                    // (a distinct namespace) arrives, so this is normally non-empty;
                    // guard defensively so a stray empty group can never crash on
                    // `agents[0].step` downstream.
                    if (!node.agents.length) return null;
                    return <SubagentTeamGroup key={node.agents[0].step.callId} group={node} />;
                }
                // Residual bare `step` node: buildTimelineGroups wraps every
                // top-level step into a deep_step_group, so this branch is a
                // defensive fallback for any future node shape. thinking is
                // already absorbed by deep_step_group; everything else degrades to
                // the appropriate lite row.
                const { step } = node;
                if (step.stepType === 'knowledge') {
                    return <KnowledgeRow key={step.callId} step={step} />;
                }
                return <ToolRowLite key={step.callId} step={step} />;
            })}
        </div>
    );
}
