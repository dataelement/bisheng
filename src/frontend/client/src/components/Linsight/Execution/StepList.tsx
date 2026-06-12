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
        <div className="flex flex-col">
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
