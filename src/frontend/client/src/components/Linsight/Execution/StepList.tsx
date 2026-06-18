/**
 * F035 Track H (P3): renders a merged step list as the proper row family —
 * dispatching on step_type per the event->UI mapping table (spec §7).
 * Used both inside TaskStepRow (per-task sub-steps) and at flow level for
 * session-scoped steps (task_id == session_version_id pseudo task).
 */
import { useMemo } from 'react';
import type { ExecStepEventData } from './stepUtils';
import { buildFlowNodes, mergeStepFrames } from './stepUtils';
import { KnowledgeRow } from './KnowledgeRow';
import { SubagentRow } from './SubagentRow';
import { ThinkingRow } from './ThinkingRow';
import { ToolRow } from './ToolRow';
import { UiCardRow } from './UiCardRow';

export function StepList({ history }: { history: ExecStepEventData[] | null | undefined }) {
    // F3 perf: building the node tree is two O(n) passes (merge + group). The WS
    // pump mutates `history` in place (same array reference), so we cannot rely on
    // the reference alone — a composite signature (length + last frame's status /
    // call_id) re-fires the memo on each appended/closed frame while skipping the
    // wasteful per-render rebuild.
    const frames = history || [];
    const last = frames[frames.length - 1];
    const sig = `${frames.length}:${last?.status ?? ''}:${last?.call_id ?? ''}`;
    const nodes = useMemo(() => buildFlowNodes(mergeStepFrames(history)), [sig]); // eslint-disable-line react-hooks/exhaustive-deps
    if (!nodes.length) return null;

    return (
        <div className="flex flex-col">
            {/* No continuous spine: each StepRow draws its own per-node connector
                while expanded (see StepRow's left rail), so the timeline reads as
                discrete segments rather than one line running through every node. */}
            {nodes.map((node) => {
                if (node.kind === 'subagent_group') {
                    // buildFlowNodes materializes a group only once it has a real
                    // agent, so this is normally non-empty; guard defensively so a
                    // stray empty group can never crash on `agents[0].step`.
                    if (!node.agents.length) return null;
                    return <SubagentRow key={node.agents[0].step.callId} group={node} />;
                }
                const { step } = node;
                switch (step.stepType) {
                    case 'knowledge':
                        return <KnowledgeRow key={step.callId} step={step} />;
                    case 'thinking':
                        return <ThinkingRow key={step.callId} step={step} />;
                    case 'ui_card':
                        return <UiCardRow key={step.callId} step={step} />;
                    case 'tool':
                    default:
                        // unknown step types degrade to the generic tool row
                        return <ToolRow key={step.callId} step={step} />;
                }
            })}
        </div>
    );
}
