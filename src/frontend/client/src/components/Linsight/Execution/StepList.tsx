/**
 * F035 Track H (P3): renders a merged step list as the proper row family —
 * dispatching on step_type per the event->UI mapping table (spec §7).
 * Used both inside TaskStepRow (per-task sub-steps) and at flow level for
 * session-scoped steps (task_id == session_version_id pseudo task).
 */
import type { ExecStepEventData } from './stepUtils';
import { buildFlowNodes, mergeStepFrames } from './stepUtils';
import { KnowledgeRow } from './KnowledgeRow';
import { SubagentRow } from './SubagentRow';
import { ThinkingRow } from './ThinkingRow';
import { ToolRow } from './ToolRow';
import { UiCardRow } from './UiCardRow';

export function StepList({ history }: { history: ExecStepEventData[] | null | undefined }) {
    const nodes = buildFlowNodes(mergeStepFrames(history));
    if (!nodes.length) return null;

    return (
        <div className="relative flex flex-col">
            {/* Timeline spine: vertical line through the leading-icon centers, so
                each step icon reads as a node on the line. The left offset (left-2
                ≈ icon center) and top-3/bottom-3 insets are visually tunable. */}
            <span aria-hidden className="pointer-events-none absolute left-2 top-3 bottom-3 w-px bg-gray-200" />
            {nodes.map((node) => {
                if (node.kind === 'subagent_group') {
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
