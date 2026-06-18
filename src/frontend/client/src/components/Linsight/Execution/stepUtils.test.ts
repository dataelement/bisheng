import {
    buildFlowNodes,
    buildTimelineGroups,
    extractNarration,
    firstLine,
    mergeStepFrames,
    narrationFromSteps,
    summarizeActivity,
} from './stepUtils';
import type { DeepStepGroup, ExecStepEventData, MergedStep, SubagentGroup } from './stepUtils';

// These frames mirror the REAL persisted history contract (ExecStep.model_dump()):
// the subgraph namespace lives in extra_info.namespace and a second-level int
// timestamp is top-level. Shape approximates the 114-field replay: ONE main-graph
// `task` delegation (ns=None, step_type='subagent') followed by THREE distinct
// flat tools:<uuid> subagents, each running tool/knowledge/thinking steps.
// Source of truth: src/backend/test/linsight/fixtures/ws_events/step_types.json
//                  + 《灵思任务模式执行流渲染优化方案》§5

/** Build a frame with sensible defaults. */
function frame(over: Partial<ExecStepEventData>): ExecStepEventData {
    return {
        task_id: 't1',
        status: 'end',
        params: {},
        output: null,
        extra_info: {},
        ...over,
    };
}

/** A subagent-internal step under a given flat tools:<uuid> namespace. */
function nsStep(ns: string, over: Partial<ExecStepEventData>): ExecStepEventData {
    return frame({ ...over, extra_info: { ...(over.extra_info || {}), namespace: ns } });
}

// The B2 main-graph delegation anchor: ns=None, step_type='subagent',
// name=general-purpose, call_reason/delegate_goal carry the goal.
const delegation: ExecStepEventData = frame({
    call_id: 'call_task_01',
    name: 'general-purpose',
    step_type: 'subagent',
    status: 'start',
    call_reason: '调研三大框架对比',
    params: { subagent_type: 'general-purpose', description: '调研三大框架对比' },
    extra_info: { delegate_goal: '调研三大框架对比' },
    timestamp: 100,
});

const NS_A = 'tools:11111111-1111-1111-1111-111111111111';
const NS_B = 'tools:22222222-2222-2222-2222-222222222222';
const NS_C = 'tools:33333333-3333-3333-3333-333333333333';

describe('stepUtils — firstLine (A)', () => {
    it('returns empty string for empty / nullish input', () => {
        expect(firstLine('')).toBe('');
        expect(firstLine(null)).toBe('');
        expect(firstLine(undefined)).toBe('');
        expect(firstLine('   \n  ')).toBe('');
    });

    it('strips newlines and trims', () => {
        expect(firstLine('  hello\nworld  ')).toBe('hello world');
    });

    it('truncates long text to ~24 chars with an ellipsis', () => {
        const long = 'a'.repeat(50);
        const out = firstLine(long);
        expect(out.endsWith('…')).toBe(true);
        // 24 chars + ellipsis
        expect(out.length).toBe(25);
    });

    it('prefers the first sentence when it fits the budget', () => {
        expect(firstLine('对齐口径。然后再算同比。')).toBe('对齐口径。');
    });
});

describe('stepUtils — timestamp -> startedAt/endedAt (B)', () => {
    it('reads startedAt from the first frame and endedAt from the latest', () => {
        const frames: ExecStepEventData[] = [
            frame({ call_id: 'c1', name: 'thinking', step_type: 'thinking', status: 'start', output: '想', timestamp: 10 }),
            frame({ call_id: 'c1', name: 'thinking', step_type: 'thinking', status: 'end', output: '想完了', timestamp: 18 }),
        ];
        const [merged] = mergeStepFrames(frames);
        expect(merged.startedAt).toBe(10);
        expect(merged.endedAt).toBe(18);
    });
});

describe('stepUtils — subagent grouping by distinct namespace (D)', () => {
    // 1 delegation + 3 distinct ns subagents, each with tool/knowledge/thinking.
    const history: ExecStepEventData[] = [
        delegation,
        nsStep(NS_A, { call_id: 'a_think', name: 'thinking', step_type: 'thinking', output: '思路A', timestamp: 101 }),
        nsStep(NS_A, { call_id: 'a_tool', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 102 }),
        nsStep(NS_B, { call_id: 'b_know', name: 'search_knowledge_base', step_type: 'knowledge', output: '竞品', timestamp: 103 }),
        nsStep(NS_B, { call_id: 'b_tool', name: 'write_file', step_type: 'tool', output: 'ok', timestamp: 104 }),
        nsStep(NS_C, { call_id: 'c_tool', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 105 }),
    ];

    it('folds 3 distinct namespaces into ONE team group with agents.length === 3 (22→3)', () => {
        const nodes = buildFlowNodes(mergeStepFrames(history));
        const groups = nodes.filter((n): n is SubagentGroup => n.kind === 'subagent_group');
        expect(groups).toHaveLength(1);
        const group = groups[0];
        expect(group.name).toBe('general-purpose');
        expect(group.agents).toHaveLength(3);
        // delegation goal surfaces on the group header
        expect(group.goals).toContain('调研三大框架对比');
        // each distinct ns becomes a 1-based agent
        expect(group.agents.map((a) => a.idx)).toEqual([1, 2, 3]);
    });

    it('subagent-internal steps are NOT mislabeled as subagent (B1 dropped that rule)', () => {
        const nodes = buildFlowNodes(mergeStepFrames(history));
        const group = nodes.find((n): n is SubagentGroup => n.kind === 'subagent_group')!;
        const agentB = group.agents[1];
        // first step seen under NS_B is the knowledge frame, kept as 'knowledge'
        expect(agentB.step.stepType).toBe('knowledge');
        expect(agentB.step.name).toBe('search_knowledge_base');
        // its later same-ns step folds in as a child
        expect(agentB.children).toHaveLength(1);
        expect(agentB.children[0].name).toBe('write_file');
    });
});

describe('stepUtils — adjacent thinking merge (C)', () => {
    it('merges consecutive same-namespace thinking into one passage (joined seamlessly — deltas carry their own spacing)', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 't_a', name: 'thinking', step_type: 'thinking', output: '第一段', timestamp: 1 }),
            frame({ call_id: 't_b', name: 'thinking', step_type: 'thinking', output: '第二段', timestamp: 2 }),
        ];
        const nodes = buildFlowNodes(mergeStepFrames(history));
        expect(nodes).toHaveLength(1);
        expect(nodes[0].kind).toBe('step');
        const step = nodes[0].kind === 'step' ? nodes[0].step : null;
        expect(step!.output).toBe('第一段第二段');
        // earliest start, latest end, first item's callId
        expect(step!.startedAt).toBe(1);
        expect(step!.endedAt).toBe(2);
        expect(step!.callId).toBe('t_a');
    });

    it('does NOT merge thinking across different namespaces (no cross-subagent contamination)', () => {
        const history: ExecStepEventData[] = [
            delegation,
            nsStep(NS_A, { call_id: 'a_think', name: 'thinking', step_type: 'thinking', output: 'A 想', timestamp: 1 }),
            nsStep(NS_B, { call_id: 'b_think', name: 'thinking', step_type: 'thinking', output: 'B 想', timestamp: 2 }),
        ];
        const nodes = buildFlowNodes(mergeStepFrames(history));
        const group = nodes.find((n): n is SubagentGroup => n.kind === 'subagent_group')!;
        // two distinct ns => two agents, each holding its own thinking, not merged
        expect(group.agents).toHaveLength(2);
        expect(group.agents[0].step.output).toBe('A 想');
        expect(group.agents[1].step.output).toBe('B 想');
    });

    it('does NOT merge a non-thinking step sitting between two thinking steps', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 't1', name: 'thinking', step_type: 'thinking', output: '想1', timestamp: 1 }),
            frame({ call_id: 'k1', name: 'search_knowledge_base', step_type: 'knowledge', output: '检索', timestamp: 2 }),
            frame({ call_id: 't2', name: 'thinking', step_type: 'thinking', output: '想2', timestamp: 3 }),
        ];
        const nodes = buildFlowNodes(mergeStepFrames(history));
        expect(nodes).toHaveLength(3);
    });
});

describe('stepUtils — orphan namespaced step (defensive inline)', () => {
    it('renders an orphan namespaced step inline rather than dropping or crashing', () => {
        const orphan = nsStep(NS_A, { call_id: 'orphan_01', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 9 });
        const nodes = buildFlowNodes(mergeStepFrames([orphan]));
        expect(nodes).toHaveLength(1);
        expect(nodes[0].kind).toBe('step');
        const step = nodes[0].kind === 'step' ? nodes[0].step : null;
        expect(step!.callId).toBe('orphan_01');
    });
});

describe('stepUtils — top-level steps stay inline alongside team groups', () => {
    it('keeps a top-level tool inline and folds namespaced steps under the team group', () => {
        const topLevelTool = frame({
            call_id: 'call_tool_01',
            name: 'bisheng_code_interpreter',
            step_type: 'tool',
            output: 'ok',
            timestamp: 90,
        });
        const history: ExecStepEventData[] = [
            topLevelTool,
            delegation,
            nsStep(NS_A, { call_id: 'a_tool', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 101 }),
        ];
        const nodes = buildFlowNodes(mergeStepFrames(history));
        expect(nodes.some((n) => n.kind === 'step' && n.step.callId === 'call_tool_01')).toBe(true);
        const group = nodes.find((n): n is SubagentGroup => n.kind === 'subagent_group')!;
        expect(group.agents).toHaveLength(1);
    });
});

describe('stepUtils — buildTimelineGroups (Wave2 deep_step_group aggregation)', () => {
    it('wraps a continuous top-level thinking+tool run into ONE deep_step_group (ordered, both kinds; write_todos dropped)', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'p_think1', name: 'thinking', step_type: 'thinking', output: '先拆解问题', timestamp: 10 }),
            // write_todos is plan-only noise — dropped by mergeStepFrames, must not appear
            frame({ call_id: 'p_todos', name: 'write_todos', step_type: 'tool', output: '已写清单', timestamp: 12 }),
            frame({ call_id: 'p_tool', name: 'web_search', step_type: 'tool', output: '搜到了', timestamp: 13 }),
            frame({ call_id: 'p_know', name: 'search_knowledge_base', step_type: 'knowledge', output: '查到背景', timestamp: 14 }),
        ];
        const nodes = buildTimelineGroups(mergeStepFrames(history));
        expect(nodes).toHaveLength(1);
        expect(nodes[0].kind).toBe('deep_step_group');
        const grp = nodes[0] as DeepStepGroup;
        // write_todos is gone; remaining steps preserved in order, both kinds present
        expect(grp.steps.map((s) => s.callId)).toEqual(['p_think1', 'p_tool', 'p_know']);
        expect(grp.steps.map((s) => s.stepType)).toEqual(['thinking', 'tool', 'knowledge']);
    });

    it('a subagent_group breaks the top-level run and passes through verbatim (22→3 preserved)', () => {
        const history: ExecStepEventData[] = [
            // top-level planning run
            frame({ call_id: 'p_think', name: 'thinking', step_type: 'thinking', output: '规划', timestamp: 10 }),
            frame({ call_id: 'p_plan_tool', name: 'web_search', step_type: 'tool', output: '查', timestamp: 11 }),
            // delegation + 3 distinct subagents
            delegation,
            nsStep(NS_A, { call_id: 'a_tool', name: 'web_search', step_type: 'tool', output: 'a', timestamp: 101 }),
            nsStep(NS_B, { call_id: 'b_tool', name: 'web_search', step_type: 'tool', output: 'b', timestamp: 102 }),
            nsStep(NS_C, { call_id: 'c_tool', name: 'web_search', step_type: 'tool', output: 'c', timestamp: 103 }),
        ];
        const nodes = buildTimelineGroups(mergeStepFrames(history));
        // [deep_step_group(planning), subagent_group(3 agents)]
        expect(nodes.map((n) => n.kind)).toEqual(['deep_step_group', 'subagent_group']);
        const team = nodes[1] as SubagentGroup;
        expect(team.agents).toHaveLength(3);
        // the leading planning run aggregated into one episode
        const planning = nodes[0] as DeepStepGroup;
        expect(planning.steps.map((s) => s.callId)).toEqual(['p_think', 'p_plan_tool']);
    });

    it('keeps top-level runs on BOTH sides of a subagent_group as separate deep_step_groups', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'pre', name: 'thinking', step_type: 'thinking', output: '前', timestamp: 10 }),
            delegation,
            nsStep(NS_A, { call_id: 'a_tool', name: 'web_search', step_type: 'tool', output: 'a', timestamp: 20 }),
            // a top-level step after the burst closes the group and opens a new run
            frame({ call_id: 'post', name: 'thinking', step_type: 'thinking', output: '汇总结果', timestamp: 30 }),
        ];
        const nodes = buildTimelineGroups(mergeStepFrames(history));
        expect(nodes.map((n) => n.kind)).toEqual(['deep_step_group', 'subagent_group', 'deep_step_group']);
        expect((nodes[0] as DeepStepGroup).steps.map((s) => s.callId)).toEqual(['pre']);
        expect((nodes[2] as DeepStepGroup).steps.map((s) => s.callId)).toEqual(['post']);
    });

    it('deep_step_group startedAt/endedAt span the whole episode range, running = any step running', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 's1', name: 'thinking', step_type: 'thinking', status: 'end', output: 'a', timestamp: 5 }),
            frame({ call_id: 's2', name: 'web_search', step_type: 'tool', status: 'start', output: 'b', timestamp: 8 }),
        ];
        const [grp] = buildTimelineGroups(mergeStepFrames(history)) as DeepStepGroup[];
        expect(grp.kind).toBe('deep_step_group');
        expect(grp.startedAt).toBe(5);
        expect(grp.endedAt).toBe(8);
        // s2 has no end frame -> still running -> group is running
        expect(grp.running).toBe(true);
    });

    it('a lone top-level step is still wrapped in a deep_step_group (uniform render)', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'only', name: 'thinking', step_type: 'thinking', output: '一句话', timestamp: 1 }),
        ];
        const nodes = buildTimelineGroups(mergeStepFrames(history));
        expect(nodes).toHaveLength(1);
        expect(nodes[0].kind).toBe('deep_step_group');
        expect((nodes[0] as DeepStepGroup).steps).toHaveLength(1);
    });

    it('drill-down: a subagent\'s pure thinking+tool children aggregate into deep_step_groups', () => {
        // SubagentTrack feeds one agent's children (no delegation frame, namespaced
        // tool/thinking) back into buildTimelineGroups for the L3 view.
        const history: ExecStepEventData[] = [
            delegation,
            nsStep(NS_A, { call_id: 'c_think', name: 'thinking', step_type: 'thinking', output: '子代理思路', timestamp: 50 }),
            nsStep(NS_A, { call_id: 'c_tool', name: 'web_search', step_type: 'tool', output: '搜到了', timestamp: 51 }),
            nsStep(NS_A, { call_id: 'c_write', name: 'write_file', step_type: 'tool', output: '写好了', timestamp: 52 }),
        ];
        const group = buildFlowNodes(mergeStepFrames(history)).find(
            (n): n is SubagentGroup => n.kind === 'subagent_group',
        )!;
        const agent = group.agents[0];
        // the agent's own anchor step + its children form the full child timeline
        const childSteps = [agent.step, ...agent.children];
        const nodes = buildTimelineGroups(childSteps);
        // no subagent_group inside (children carry namespace but no delegation
        // opened this run -> orphan inline -> all wrapped into one deep_step_group)
        expect(nodes).toHaveLength(1);
        expect(nodes[0].kind).toBe('deep_step_group');
        const grp = nodes[0] as DeepStepGroup;
        expect(grp.steps.map((s) => s.callId)).toEqual(['c_think', 'c_tool', 'c_write']);
        expect(grp.steps.some((s) => s.stepType === 'thinking')).toBe(true);
        expect(grp.steps.some((s) => s.stepType === 'tool')).toBe(true);
    });
});

describe('stepUtils — lazy team group (empty-group crash regression)', () => {
    it('task delegations with NO children yet emit NO subagent_group (no agents[0].step crash)', () => {
        // The live streaming window: 3 `task` frames arrived, subgraph children have
        // not streamed in yet. An eager group here had empty `agents` → StepList
        // crashed on `node.agents[0].step.callId` ("Cannot read properties of
        // undefined (reading 'step')"). Lazy creation must emit no group at all.
        const history: ExecStepEventData[] = [
            { ...delegation, call_id: 'task1' },
            { ...delegation, call_id: 'task2' },
            { ...delegation, call_id: 'task3' },
        ];
        const nodes = buildFlowNodes(mergeStepFrames(history));
        expect(nodes.some((n) => n.kind === 'subagent_group')).toBe(false);
        // every emitted group (none here) must be non-empty — assert the invariant
        nodes.forEach((n) => {
            if (n.kind === 'subagent_group') expect(n.agents.length).toBeGreaterThan(0);
        });
    });

    it('once children stream in, the pending delegations fold into ONE non-empty group', () => {
        const history: ExecStepEventData[] = [
            { ...delegation, call_id: 'task1' },
            { ...delegation, call_id: 'task2' },
            nsStep(NS_A, { call_id: 'a1', name: 'web_search', step_type: 'tool', output: 'x', timestamp: 110 }),
            nsStep(NS_B, { call_id: 'b1', name: 'web_search', step_type: 'tool', output: 'y', timestamp: 111 }),
        ];
        const nodes = buildFlowNodes(mergeStepFrames(history));
        const groups = nodes.filter((n): n is SubagentGroup => n.kind === 'subagent_group');
        expect(groups).toHaveLength(1);
        expect(groups[0].agents).toHaveLength(2);
        expect(groups[0].goals).toContain('调研三大框架对比');
    });
});

describe('stepUtils — write_todos exclusion (mergeStepFrames discard set)', () => {
    it('drops write_todos frames entirely (plan is owned by the bottom TaskPanel)', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'k1', name: 'think', step_type: 'thinking', output: '想', timestamp: 1 }),
            frame({ call_id: 'k2', name: 'write_todos', step_type: 'tool', output: '清单', timestamp: 2 }),
            frame({ call_id: 'k3', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 3 }),
        ];
        const merged = mergeStepFrames(history);
        expect(merged.map((s) => s.name)).toEqual(['think', 'web_search']);
        expect(merged.some((s) => s.name === 'write_todos')).toBe(false);
    });

    it('still drops ask_user and ls alongside write_todos (full discard set)', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'a', name: 'ask_user', step_type: 'tool', status: 'start', timestamp: 1 }),
            frame({ call_id: 'b', name: 'ls', step_type: 'tool', output: '', timestamp: 2 }),
            frame({ call_id: 'c', name: 'write_todos', step_type: 'tool', output: 'x', timestamp: 3 }),
            frame({ call_id: 'd', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 4 }),
        ];
        const merged = mergeStepFrames(history);
        expect(merged.map((s) => s.name)).toEqual(['web_search']);
    });
});

// helper: build a minimal MergedStep for the pure-function tests
function step(over: Partial<MergedStep>): MergedStep {
    return {
        callId: over.callId || 'c',
        taskId: 't1',
        name: over.name || '',
        stepType: over.stepType || 'tool',
        running: over.running ?? false,
        callReason: '',
        params: null,
        output: over.output ?? '',
        namespace: over.namespace ?? null,
        extraInfo: {},
        startedAt: over.startedAt,
        endedAt: over.endedAt,
        raw: {} as ExecStepEventData,
        ...over,
    };
}

describe('stepUtils — summarizeActivity (§3 readable activity meta)', () => {
    it('classifies by tool name and sorts by count descending', () => {
        const steps: MergedStep[] = [
            step({ name: 'web_search', stepType: 'tool' }),
            step({ name: 'web_search', stepType: 'tool' }),
            step({ name: 'web_search', stepType: 'tool' }),
            step({ name: 'search_knowledge_base', stepType: 'knowledge' }),
            step({ name: 'export_pdf', stepType: 'tool' }),
            step({ name: 'export_docx', stepType: 'tool' }),
        ];
        const out = summarizeActivity(steps);
        // web_search(3) > export(2) > knowledge(1), descending by count
        expect(out).toEqual([
            { category: 'web_search', count: 3 },
            { category: 'export', count: 2 },
            { category: 'knowledge', count: 1 },
        ]);
    });

    it('routes knowledge before web_search (search_knowledge_base != web_search)', () => {
        const out = summarizeActivity([step({ name: 'search_knowledge_base', stepType: 'knowledge' })]);
        expect(out).toEqual([{ category: 'knowledge', count: 1 }]);
    });

    it('maps the write/read/code/browse families to their categories', () => {
        const steps: MergedStep[] = [
            step({ name: 'write_file', stepType: 'tool' }),
            step({ name: 'add_text_to_file', stepType: 'tool' }),
            step({ name: 'read_file', stepType: 'tool' }),
            step({ name: 'bisheng_code_interpreter', stepType: 'tool' }),
            step({ name: 'glob', stepType: 'tool' }),
            step({ name: 'grep', stepType: 'tool' }),
        ];
        const map = Object.fromEntries(summarizeActivity(steps).map((a) => [a.category, a.count]));
        expect(map.write_file).toBe(2);
        expect(map.read_file).toBe(1);
        expect(map.code).toBe(1);
        expect(map.browse).toBe(2);
    });

    it('excludes thinking / ls / write_todos / ask_user, buckets unknown tools as other', () => {
        const steps: MergedStep[] = [
            step({ name: 'thinking', stepType: 'thinking', output: '想' }),
            step({ name: 'ls', stepType: 'tool' }),
            step({ name: 'write_todos', stepType: 'tool' }),
            step({ name: 'ask_user', stepType: 'tool' }),
            step({ name: 'some_unknown_mcp_tool', stepType: 'tool' }),
        ];
        const out = summarizeActivity(steps);
        expect(out).toEqual([{ category: 'other', count: 1 }]);
    });

    it('returns [] for a pure-thinking group / empty input', () => {
        expect(summarizeActivity([step({ name: 'thinking', stepType: 'thinking', output: 'x' })])).toEqual([]);
        expect(summarizeActivity([])).toEqual([]);
        expect(summarizeActivity(null)).toEqual([]);
    });
});

describe('stepUtils — extractNarration (§3 narration 旁白)', () => {
    it('returns the last sentence after stripping markdown / code', () => {
        const text = '## 计划\n我先看看 `workspace` 有什么。我需要先看看工作区有什么文件，找到之前写的报告。';
        expect(extractNarration(text)).toBe('我需要先看看工作区有什么文件，找到之前写的报告。');
    });

    it('strips fenced code blocks and takes the trailing narration', () => {
        const text = 'Let me run it.\n```python\nprint(1)\n```\nI just need to call the export tool.';
        expect(extractNarration(text)).toBe('I just need to call the export tool.');
    });

    it('falls back to the previous sentence when the last one is too short', () => {
        const text = '我已经完成了生平与从政时间线的整理。好。';
        expect(extractNarration(text)).toBe('我已经完成了生平与从政时间线的整理。');
    });

    it('returns empty string for empty / code-only input', () => {
        expect(extractNarration('')).toBe('');
        expect(extractNarration(null)).toBe('');
        expect(extractNarration('```py\nx=1\n```')).toBe('');
    });
});

describe('stepUtils — narrationFromSteps (§3 running vs done)', () => {
    it('running -> the latest thinking passage last sentence', () => {
        const steps: MergedStep[] = [
            step({ name: 'thinking', stepType: 'thinking', output: '第一段思考。先看资料。' }),
            step({ name: 'web_search', stepType: 'tool', output: 'hit' }),
            step({ name: 'thinking', stepType: 'thinking', output: '现在我要开始动手写报告了。', running: true }),
        ];
        expect(narrationFromSteps(steps, true)).toBe('现在我要开始动手写报告了。');
    });

    it('done -> the final thinking passage last sentence', () => {
        const steps: MergedStep[] = [
            step({ name: 'thinking', stepType: 'thinking', output: '开始。先列大纲。' }),
            step({ name: 'thinking', stepType: 'thinking', output: '已界定范围并完成权威来源核实。' }),
        ];
        expect(narrationFromSteps(steps, false)).toBe('已界定范围并完成权威来源核实。');
    });

    it('returns empty string when there is no thinking step', () => {
        expect(narrationFromSteps([step({ name: 'web_search', stepType: 'tool' })], false)).toBe('');
        expect(narrationFromSteps([], true)).toBe('');
    });
});
