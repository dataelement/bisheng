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
import { useExecutionLive } from './executionLive';
import { IntentRow } from './IntentRow';
import { KnowledgeRow } from './KnowledgeRow';
import { ToolRowLite } from './ToolRowLite';
import type { ExecStepEventData } from './stepUtils';
import { buildTimelineGroups, explodeSubagentGroup, mergeStepFrames } from './stepUtils';

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
    // Container liveness (session turn / running task), provided by the carrier via
    // ExecutionLiveContext. The ACTIVE episode is the LAST node while the container
    // is live — that one carries the live facets (正在 label, header pulse, ticking
    // clock); every earlier node is done. (The fold itself opens collapsed for all
    // groups — see DeepStepGroup.) Passing this stable `active` down (instead of
    // letting each group read the volatile per-tool group.running) is what stops the
    // label/pulse from flickering on every tool call within one episode.
    const live = useExecutionLive();
    if (!nodes.length) return null;
    const lastIdx = nodes.length - 1;

    return (
        // Group spacing aligns with the daily /c stack (gap-3 between groups).
        <div className="flex flex-col gap-3">
            {nodes.map((node, idx) => {
                const active = live && idx === lastIdx;
                // Inline answered clarify (时序内联): an "已经明确用户意图" summary row
                // sitting between the pre-question thinking and the resumed thinking.
                // Always collapsed (no `active`) — it is a record, not a live episode.
                if (node.kind === 'intent') {
                    return <IntentRow key={`intent_${idx}`} data={node.data} />;
                }
                if (node.kind === 'deep_step_group') {
                    // Stable key: first step's callId; fall back to index when an
                    // episode somehow has no steps (defensive — flush() never emits
                    // an empty episode, so this is a belt-and-braces guard).
                    const key = node.steps[0]?.callId ?? `deep_${idx}`;
                    return <DeepStepGroup key={key} group={node} active={active} />;
                }
                if (node.kind === 'subagent_group') {
                    // buildFlowNodes materializes a group only once a real subagent
                    // (a distinct namespace) arrives, so this is normally non-empty;
                    // guard defensively so a stray empty group can never crash.
                    if (!node.agents.length) return null;
                    // R3 完全拆平 (2026-06): dissolve the team shell — render each
                    // subagent as its own flat top-level segment via the shared
                    // DeepStepGroup, headed by its delegation goal + activity summary
                    // and a distinct agent rail icon. (Trade-off accepted in §1.3:
                    // the explicit "N parallel subagents" grouping signal is dropped.)
                    // While this team is the live tail (active), all its parallel
                    // segments are in-progress, so each gets active=true (expanded);
                    // once superseded they all collapse together.
                    return explodeSubagentGroup(node).map((seg, sIdx) => (
                        <DeepStepGroup
                            key={seg.steps[0]?.callId ?? `sub_${idx}_${sIdx}`}
                            group={{
                                kind: 'deep_step_group',
                                steps: seg.steps,
                                startedAt: seg.startedAt,
                                endedAt: seg.endedAt,
                                running: seg.running,
                            }}
                            subagent={{ goal: seg.goal, idx: seg.idx }}
                            active={active}
                        />
                    ));
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
