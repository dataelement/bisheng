import { buildFlowNodes, mergeStepFrames } from './stepUtils';
import type { ExecStepEventData } from './stepUtils';

// These frames mirror the REAL backend contract (ExecStep.model_dump()): the
// subgraph namespace lives in extra_info.namespace, NOT a top-level field.
// Source of truth: src/backend/test/linsight/fixtures/ws_events/step_types.json
// Regression guard for design #1 (subagent re-introduction): the backend emits
// namespace under extra_info, so the folding must read it from there.
const topLevelTool: ExecStepEventData = {
    call_id: 'call_tool_01',
    task_id: 't1',
    name: 'bisheng_code_interpreter',
    step_type: 'tool',
    status: 'end',
    params: {},
    output: 'ok',
    extra_info: { truncated: false },
};

const subagentStart: ExecStepEventData = {
    call_id: 'call_sub_01',
    task_id: 't1',
    name: 'general-purpose',
    step_type: 'subagent',
    status: 'start',
    params: { instruction: '对标三家同行毛利率' },
    output: null,
    extra_info: { truncated: false, namespace: 'general-purpose:0' },
};

const subagentChild: ExecStepEventData = {
    call_id: 'call_sub_inner_01',
    task_id: 't1',
    name: 'search_knowledge_base',
    step_type: 'knowledge',
    status: 'end',
    params: { query: '同行毛利率' },
    output: '竞品 A 32% ...',
    extra_info: { truncated: false, namespace: 'general-purpose:0' },
};

describe('stepUtils — subagent namespace folding (design #1)', () => {
    it('mergeStepFrames reads namespace from extra_info.namespace (real backend contract)', () => {
        const [merged] = mergeStepFrames([subagentStart]);
        expect(merged.namespace).toBe('general-purpose:0');
        expect(merged.stepType).toBe('subagent');
    });

    it('falls back to a legacy top-level namespace when extra_info carries none', () => {
        const legacy: ExecStepEventData = {
            ...subagentChild,
            extra_info: { truncated: false },
            namespace: 'legacy:0',
        };
        const [merged] = mergeStepFrames([legacy]);
        expect(merged.namespace).toBe('legacy:0');
    });

    it('buildFlowNodes folds namespaced children under their subagent group', () => {
        const nodes = buildFlowNodes(mergeStepFrames([topLevelTool, subagentStart, subagentChild]));

        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- narrow the FlowNode union for assertions
        const group: any = nodes.find((n) => n.kind === 'subagent_group');
        expect(group).toBeDefined();
        expect(group.agents).toHaveLength(1);
        expect(group.agents[0].children).toHaveLength(1);
        expect(group.agents[0].children[0].callId).toBe('call_sub_inner_01');

        // the top-level tool stays inline, NOT folded into a subagent group
        expect(nodes.some((n) => n.kind === 'step' && n.step.callId === 'call_tool_01')).toBe(true);
    });

    it('orphan namespaced step (no matching subagent) renders inline, not dropped', () => {
        const orphan: ExecStepEventData = { ...subagentChild, call_id: 'orphan_01' };
        const nodes = buildFlowNodes(mergeStepFrames([orphan]));
        expect(nodes).toHaveLength(1);
        expect(nodes[0].kind).toBe('step');
    });
});
