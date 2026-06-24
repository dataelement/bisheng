import {
    activeFlowNode,
    buildFlowNodes,
    buildTimelineGroups,
    explodeSubagentGroup,
    extractNarration,
    findPendingUserInput,
    firstLine,
    mergeStepFrames,
    narrationFromSteps,
    parseClarifyRequest,
    summarizeActivity,
} from './stepUtils';
import type { DeepStepGroup, ExecStepEventData, IntentNode, MergedStep, SubagentGroup } from './stepUtils';

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

    it('honors a custom budget — returns the first sentence intact when it fits (subagent title)', () => {
        // The subagent card passes a widened budget (~48) so a typical delegation
        // goal's first sentence survives instead of being chopped at 24.
        const goal = '调研中际旭创（股票代码：300308）的公司基本信息与业务概况。请检索并返回以下内容的蒸馏摘要。';
        // first sentence (≤ 48) → returned whole, the trailing detail sentence dropped
        expect(firstLine(goal, 48)).toBe('调研中际旭创（股票代码：300308）的公司基本信息与业务概况。');
    });

    it('honors a custom budget — hard-truncates a first sentence that exceeds it', () => {
        const long = 'a'.repeat(60) + '。';
        const out = firstLine(long, 48);
        expect(out.endsWith('…')).toBe(true);
        expect(out.length).toBe(49); // 48 chars + ellipsis
    });

    it('does not break at a mid-token ASCII dot (ticker / decimal / abbreviation)', () => {
        // The "." in "601138.SH" is followed by a letter, NOT whitespace/end — so it
        // is not a sentence boundary; the real break is the 。 after 公司基本信息.
        const goal = '请调研工业富联（富士康工业互联网股份有限公司，股票代码601138.SH）的公司基本信息。请汇总。';
        expect(firstLine(goal, 100)).toBe('请调研工业富联（富士康工业互联网股份有限公司，股票代码601138.SH）的公司基本信息。');
        // a decimal point mid-number is likewise not a boundary
        expect(firstLine('毛利率 3.5 个百分点。', 50)).toBe('毛利率 3.5 个百分点。');
    });

    it('still treats an ASCII period as a boundary when it ends an English sentence', () => {
        expect(firstLine('Let me organize all findings. Then deliver.', 80)).toBe(
            'Let me organize all findings.',
        );
    });

    it('cuts a numbered-enumeration goal to its lead-in (no dangling "1.")', () => {
        // a delegation goal "<lead-in>：1. … 2. …" — keep the instruction, drop the list
        const goal = '研究首尔美食探店攻略，请搜索并整理以下信息：\n1. 必吃餐厅\n2. 人均消费\n3. 交通方式';
        expect(firstLine(goal, 48)).toBe('研究首尔美食探店攻略，请搜索并整理以下信息');
    });

    it('does not treat a list ordinal "1." as a sentence boundary', () => {
        expect(firstLine('计划：1. 调研 2. 写作', 24)).toBe('计划');
        // a goal that LEADS with a list marker drops the marker and keeps the first
        // item, then cuts the rest of the enumeration
        expect(firstLine('1. 调研行业 2. 写报告 3. 复核', 24)).toBe('调研行业');
    });

    it('strips markdown markers / inline code from the gist', () => {
        // inline code is unwrapped, not shown as raw `backticks`
        expect(firstLine('整理 `新易盛` 的财务数据。', 48)).toBe('整理 新易盛 的财务数据。');
        // a leading bullet the goal opens with is dropped
        expect(firstLine('- 调研行业概况', 24)).toBe('调研行业概况');
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
    it('cuts a segment at each write_todos boundary; the marker itself is never rendered (段流重构)', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'p_think1', name: 'thinking', step_type: 'thinking', output: '先拆解问题', timestamp: 10 }),
            // write_todos is the SEGMENT BOUNDARY (段流): it closes the planning
            // episode but never renders as a row.
            frame({ call_id: 'p_todos', name: 'write_todos', step_type: 'tool', output: '已写清单', timestamp: 12 }),
            frame({ call_id: 'p_tool', name: 'web_search', step_type: 'tool', output: '搜到了', timestamp: 13 }),
            frame({ call_id: 'p_know', name: 'search_knowledge_base', step_type: 'knowledge', output: '查到背景', timestamp: 14 }),
        ];
        const nodes = buildTimelineGroups(mergeStepFrames(history));
        // two segments split at write_todos: [thinking] | [web_search, knowledge]
        expect(nodes.map((n) => n.kind)).toEqual(['deep_step_group', 'deep_step_group']);
        expect((nodes[0] as DeepStepGroup).steps.map((s) => s.callId)).toEqual(['p_think1']);
        expect((nodes[1] as DeepStepGroup).steps.map((s) => s.callId)).toEqual(['p_tool', 'p_know']);
        // write_todos never appears as a rendered step in ANY segment
        const allSteps = nodes.flatMap((n) => (n as DeepStepGroup).steps);
        expect(allSteps.some((s) => s.name === 'write_todos')).toBe(false);
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
        // buildTimelineGroups is general-purpose: fed one agent's children (no
        // delegation frame, namespaced tool/thinking) it collapses them to
        // deep_step_groups — the same primitive the exploded-subagent path reuses.
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

describe('stepUtils — write_todos segment boundary (段流重构)', () => {
    it('keeps a main-graph write_todos through merge but cuts a segment on it (never a rendered row)', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'k1', name: 'think', step_type: 'thinking', output: '想', timestamp: 1 }),
            frame({ call_id: 'k2', name: 'write_todos', step_type: 'tool', output: '清单', timestamp: 2 }),
            frame({ call_id: 'k3', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 3 }),
        ];
        // the frame survives merge — it is the boundary signal...
        const merged = mergeStepFrames(history);
        expect(merged.some((s) => s.name === 'write_todos')).toBe(true);
        // ...but buildTimelineGroups cuts at it and never renders it as a step
        const nodes = buildTimelineGroups(merged);
        expect(nodes.map((n) => n.kind)).toEqual(['deep_step_group', 'deep_step_group']);
        const allSteps = nodes.flatMap((n) => (n as DeepStepGroup).steps);
        expect(allSteps.map((s) => s.name)).toEqual(['think', 'web_search']);
        expect(allSteps.some((s) => s.name === 'write_todos')).toBe(false);
    });

    it('drops a subagent-internal (namespaced) write_todos as noise — never a boundary or row', () => {
        const history: ExecStepEventData[] = [
            delegation,
            nsStep(NS_A, { call_id: 'a_think', name: 'thinking', step_type: 'thinking', output: '子代理思路', timestamp: 50 }),
            nsStep(NS_A, { call_id: 'a_todos', name: 'write_todos', step_type: 'tool', output: 'x', timestamp: 51 }),
            nsStep(NS_A, { call_id: 'a_tool', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 52 }),
        ];
        const group = buildFlowNodes(mergeStepFrames(history)).find(
            (n): n is SubagentGroup => n.kind === 'subagent_group',
        )!;
        const agent = group.agents[0];
        const childNames = [agent.step, ...agent.children].map((s) => s.name);
        // the namespaced write_todos is dropped from the subagent's children
        expect(childNames).not.toContain('write_todos');
        expect(childNames).toEqual(['thinking', 'web_search']);
    });

    it('still drops ask_user and ls (write_todos is no longer in the discard set)', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'a', name: 'ask_user', step_type: 'tool', status: 'start', timestamp: 1 }),
            frame({ call_id: 'b', name: 'ls', step_type: 'tool', output: '', timestamp: 2 }),
            frame({ call_id: 'd', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 4 }),
        ];
        const merged = mergeStepFrames(history);
        expect(merged.map((s) => s.name)).toEqual(['web_search']);
    });
});

describe('stepUtils — call_user_input inline IntentRow (时序内联)', () => {
    // A planning-phase clarify: thinking → ask_user(answered) → resumed thinking,
    // all before the first write_todos (so without the inline cut both thinkings
    // would merge into ONE deep_step_group hoisted below the intent). The frame is
    // a NeedUserInput model_dump: no call_id/status/name, just step_type +
    // call_reason + params.tool_calls, with is_completed/user_input stamped on
    // answer. Source: backend test/linsight/fixtures/ws_events/event_samples.json.
    const clarifyParams = {
        tool_calls: [
            { id: 'call_ui_01', name: 'ask_user', args: { question: '报告用中文还是英文？', options: ['中文', 'English'] } },
        ],
    };

    it('cuts thinking at an answered clarify: deep_step_group → intent → deep_step_group, in order', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'tA', name: 'thinking', step_type: 'thinking', output: '这些信息我不问就会做错，需要先澄清。', timestamp: 1 }),
            frame({ step_type: 'call_user_input', status: undefined, call_reason: '请确认报告输出语言', params: clarifyParams, is_completed: true, user_input: '中文', timestamp: 2 }),
            frame({ call_id: 'tB', name: 'thinking', step_type: 'thinking', output: '已澄清，开始规划行程。', timestamp: 3 }),
        ];
        const nodes = buildTimelineGroups(mergeStepFrames(history));
        // chronological order: pre-question thinking, the intent record, resumed thinking
        expect(nodes.map((n) => n.kind)).toEqual(['deep_step_group', 'intent', 'deep_step_group']);
        // the two thinkings are NOT merged across the clarify boundary
        expect((nodes[0] as DeepStepGroup).steps.map((s) => s.output)).toEqual(['这些信息我不问就会做错，需要先澄清。']);
        expect((nodes[2] as DeepStepGroup).steps.map((s) => s.output)).toEqual(['已澄清，开始规划行程。']);
    });

    it('the intent node carries the raw answered frame (parseClarifyRequest-ready)', () => {
        const history: ExecStepEventData[] = [
            frame({ step_type: 'call_user_input', status: undefined, call_reason: '请确认报告输出语言', params: clarifyParams, is_completed: true, user_input: '中文', timestamp: 2 }),
        ];
        const nodes = buildTimelineGroups(mergeStepFrames(history));
        expect(nodes).toHaveLength(1);
        const intent = nodes[0] as IntentNode;
        expect(intent.kind).toBe('intent');
        expect(intent.startedAt).toBe(2);
        expect(intent.data.is_completed).toBe(true);
        expect(intent.data.user_input).toBe('中文');
        // the same data feeds IntentRow via parseClarifyRequest
        const req = parseClarifyRequest(intent.data);
        expect(req.questions.map((q) => q.question)).toEqual(['报告用中文还是英文？']);
    });

    it('an UNANSWERED (parked) clarify produces NO intent node but still flushes the preceding episode', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'tA', name: 'thinking', step_type: 'thinking', output: '先想想要问什么。', timestamp: 1 }),
            // parked: no is_completed — surfaced as the active ClarifyCard, not here
            frame({ step_type: 'call_user_input', status: 'start', call_reason: '请确认报告输出语言', params: clarifyParams, timestamp: 2 }),
        ];
        const nodes = buildTimelineGroups(mergeStepFrames(history));
        // only the pre-question thinking episode — the clarify is dropped from the timeline
        expect(nodes.map((n) => n.kind)).toEqual(['deep_step_group']);
        expect(nodes.some((n) => n.kind === 'intent')).toBe(false);
    });

    it('activeFlowNode never surfaces a call_user_input as a collapsed-task header', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 'tA', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 1 }),
            frame({ step_type: 'call_user_input', status: undefined, call_reason: 'q', params: clarifyParams, is_completed: true, user_input: '中文', timestamp: 2 }),
        ];
        const node = activeFlowNode(history);
        expect(node).not.toBeNull();
        // falls back to the last NON-clarify node, not the clarify boundary
        expect(node!.kind === 'step' && node!.step.stepType === 'call_user_input').toBe(false);
        expect(node!.kind === 'step' && node!.step.name === 'web_search').toBe(true);
    });
});

describe('stepUtils — explodeSubagentGroup (R3 完全拆平)', () => {
    function teamOf(history: ExecStepEventData[]): SubagentGroup {
        return buildFlowNodes(mergeStepFrames(history)).find(
            (n): n is SubagentGroup => n.kind === 'subagent_group',
        )!;
    }

    it('explodes a team into one flat segment per subagent, each carrying its own steps', () => {
        const history: ExecStepEventData[] = [
            { ...delegation, call_id: 't1' },
            nsStep(NS_A, { call_id: 'a1', name: 'web_search', step_type: 'tool', output: 'a', timestamp: 100, status: 'start' }),
            nsStep(NS_A, { call_id: 'a1', name: 'web_search', step_type: 'tool', output: 'a', timestamp: 105, status: 'end' }),
            nsStep(NS_B, { call_id: 'b1', name: 'read_file', step_type: 'tool', output: 'b', timestamp: 101 }),
        ];
        const segs = explodeSubagentGroup(teamOf(history));
        expect(segs).toHaveLength(2);
        expect(segs.map((s) => s.kind)).toEqual(['subagent_segment', 'subagent_segment']);
        // each segment carries ONLY its own subagent's (namespaced) steps
        expect(segs[0].steps.every((s) => s.namespace === NS_A)).toBe(true);
        expect(segs[1].steps.every((s) => s.namespace === NS_B)).toBe(true);
        // 1-based idx + per-agent time range (a1 spans 100..105)
        expect(segs[0].idx).toBe(1);
        expect(segs[0].startedAt).toBe(100);
        expect(segs[0].endedAt).toBe(105);
    });

    it('matches goals to agents BY ORDER only when the counts are equal', () => {
        const history: ExecStepEventData[] = [
            { ...delegation, call_id: 't1', call_reason: '调研A', extra_info: { delegate_goal: '调研A' } },
            { ...delegation, call_id: 't2', call_reason: '调研B', extra_info: { delegate_goal: '调研B' } },
            nsStep(NS_A, { call_id: 'a1', name: 'web_search', step_type: 'tool', output: 'a', timestamp: 100 }),
            nsStep(NS_B, { call_id: 'b1', name: 'web_search', step_type: 'tool', output: 'b', timestamp: 101 }),
        ];
        const segs = explodeSubagentGroup(teamOf(history));
        expect(segs.map((s) => s.goal)).toEqual(['调研A', '调研B']);
    });

    it('drops goals when the burst goal count != agent count (no false binding)', () => {
        const history: ExecStepEventData[] = [
            // ONE delegation goal, but TWO subagents spawn -> cannot bind reliably
            { ...delegation, call_id: 't1', call_reason: '调研全部', extra_info: { delegate_goal: '调研全部' } },
            nsStep(NS_A, { call_id: 'a1', name: 'web_search', step_type: 'tool', output: 'a', timestamp: 100 }),
            nsStep(NS_B, { call_id: 'b1', name: 'web_search', step_type: 'tool', output: 'b', timestamp: 101 }),
        ];
        const segs = explodeSubagentGroup(teamOf(history));
        expect(segs.map((s) => s.goal)).toEqual(['', '']);
    });

    it('marks a segment running while any of its steps is unclosed', () => {
        const history: ExecStepEventData[] = [
            { ...delegation, call_id: 't1' },
            nsStep(NS_A, { call_id: 'a1', name: 'web_search', step_type: 'tool', output: 'a', timestamp: 100, status: 'start' }),
        ];
        const segs = explodeSubagentGroup(teamOf(history));
        expect(segs[0].running).toBe(true);
    });
});

describe('stepUtils — activeFlowNode (write_todos boundary never surfaces as a header)', () => {
    it('never returns a write_todos boundary node, even when it is the last frame', () => {
        const history: ExecStepEventData[] = [
            frame({ call_id: 't1', name: 'web_search', step_type: 'tool', output: 'hit', timestamp: 1 }),
            // a trailing write_todos boundary (e.g. the model marks the plan done)
            frame({ call_id: 't2', name: 'write_todos', step_type: 'tool', output: '清单', timestamp: 2 }),
        ];
        const node = activeFlowNode(history);
        expect(node).not.toBeNull();
        expect(node!.kind === 'step' && node!.step.name === 'write_todos').toBe(false);
        // it falls back to the last NON-boundary node
        expect(node!.kind === 'step' && node!.step.name === 'web_search').toBe(true);
    });

    it('returns null when the history is only boundaries / empty', () => {
        expect(activeFlowNode([])).toBeNull();
        const onlyBoundary: ExecStepEventData[] = [
            frame({ call_id: 'b', name: 'write_todos', step_type: 'tool', output: 'x', timestamp: 1 }),
        ];
        expect(activeFlowNode(onlyBoundary)).toBeNull();
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

    it('holds the last COMPLETE sentence and ignores a trailing streaming fragment', () => {
        // mid-stream: the final clause has no terminator yet -> use the prior complete one
        expect(extractNarration('先看看已有材料。我正在分析竞争格局和主要厂')).toBe('先看看已有材料。');
        // no complete sentence yet -> nothing (never surface a half-typed fragment)
        expect(extractNarration('我正在分析竞争格局')).toBe('');
        expect(extractNarration('. module competitive landscape and major vendors. I will keep going')).toBe(
            'module competitive landscape and major vendors.',
        );
    });

    it('skips a trailing non-CJK fragment in a Chinese passage', () => {
        expect(extractNarration('我要调研这家公司的行业前景与风险。Now returning to the main agent.')).toBe(
            '我要调研这家公司的行业前景与风险。',
        );
    });

    it('treats a newline as a sentence boundary (a completed line counts)', () => {
        expect(extractNarration('先列大纲\n现在开始检索资料\n')).toBe('现在开始检索资料');
    });

    it('skips an over-long instruction sentence in favor of a shorter one', () => {
        const text =
            '先摸清已有材料。' +
            '请检索并返回以下内容的蒸馏摘要需注明信息来源时间数据口径并将蒸馏后的结果完整回传给主智能体不要省略任何关键事实和数据点确保可追溯。';
        expect(extractNarration(text)).toBe('先摸清已有材料。');
    });
});

describe('stepUtils — extractNarration 选句质量 (碎片/列表/标题/数据/工具名)', () => {
    it('does NOT break a sentence at a decimal point / percent (缺陷1)', () => {
        // the "." in "76.5%" is followed by a digit, not whitespace — not a boundary,
        // so the digit-heavy financial sentence stays whole instead of "…+76." fragment
        expect(extractNarration('营收预计80亿, 同比+76.5%, 增长强劲。')).toBe(
            '营收预计80亿, 同比+76.5%, 增长强劲。',
        );
    });

    it('rejects a bare parenthesized enumeration, falling back to the prior sentence (缺陷2a)', () => {
        expect(extractNarration('我会导出多种格式。\n(markdown, html, docx, pdf)\n')).toBe(
            '我会导出多种格式。',
        );
    });

    it('prefers a terminated sentence over a title-like fragment (缺陷2b)', () => {
        expect(extractNarration('我已完成估值与风险分析。\nInvestment conclusion\n')).toBe(
            '我已完成估值与风险分析。',
        );
    });

    it('strips a leading list bullet and rejects a colon-顿号 enumeration (缺陷3)', () => {
        const text = '下面总结主要风险。\n- 风险：汇兑损失、客户集中度、竞争加剧、上游材料瓶颈\n';
        expect(extractNarration(text)).toBe('下面总结主要风险。');
    });

    it('rejects a lowercase-leading continuation fragment when a clean sentence exists (缺陷4a)', () => {
        const text = 'The model has been calibrated. confirmed, and provide uncertainty disclosures.';
        expect(extractNarration(text)).toBe('The model has been calibrated.');
    });

    it('rejects a digit-leading data enumeration in favor of the prior sentence (缺陷4b)', () => {
        const text = 'I will outline the demand drivers next. 6T, AI computing demand, etc.';
        expect(extractNarration(text)).toBe('I will outline the demand drivers next.');
    });

    it('suppresses a leaked internal tool name (缺陷5, default on)', () => {
        expect(extractNarration('先看看有什么资料。\n让我调用 ask user。')).toBe('先看看有什么资料。');
    });

    it('suppresses a leaked internal virtual-FS path (scratch/), falling back to prose', () => {
        // "notes are in scratch/." leaks the agent's private scratchpad — skip it
        expect(
            extractNarration('Compiled the key findings. All research is complete and notes are in scratch/.'),
        ).toBe('Compiled the key findings.');
        // when the scratchpad sentence is the ONLY unit, show nothing rather than leak
        expect(extractNarration('All notes are saved in scratch/.')).toBe('');
    });

    it('does NOT suppress the English idiom "from scratch" (no path slash)', () => {
        expect(extractNarration("I'll rewrite the report from scratch.")).toBe(
            "I'll rewrite the report from scratch.",
        );
    });

    it('skips a numbered outline line (Day 7: 返程) for the real English intent sentence', () => {
        // mixed passage: CJK itinerary lines are drafted CONTENT; the English intent
        // sentence is the actual aside. Day-lines must not win over it.
        expect(extractNarration('Day 7: 返程\nLet me write the plan now.')).toBe(
            'Let me write the plan now.',
        );
    });

    it('surfaces the English intent sentence over CJK outline data in a mixed passage', () => {
        const text = [
            'Let me design an optimized route:',
            'Day 1: 抵达福州，游三坊七巷',
            'Day 7: 返程',
            'Let me write out a solid plan now.',
        ].join('\n');
        expect(extractNarration(text)).toBe('Let me write out a solid plan now.');
    });

    it('still prefers a clean CJK sentence over an English plumbing tail (R-cjk demotion)', () => {
        // R-cjk is demoted, not removed — Pass 1 still grabs the CJK sentence here
        expect(
            extractNarration('我要调研这家公司的行业前景与风险。Now returning to the main agent.'),
        ).toBe('我要调研这家公司的行业前景与风险。');
    });

    it('returns "" when every unit is structural junk (no prose to surface)', () => {
        expect(extractNarration('(a, b, c)\n(d, e, f)\n')).toBe('');
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

describe('stepUtils — findPendingUserInput (park-awaiting-user signal)', () => {
    const clarify = (over: Partial<ExecStepEventData>): ExecStepEventData => ({
        step_type: 'call_user_input',
        ...over,
    });

    it('returns null when there is no clarify at all', () => {
        expect(findPendingUserInput([], [])).toBeNull();
        expect(findPendingUserInput([{ step_type: 'thinking' }], [])).toBeNull();
    });

    it('returns the unanswered session-level clarify (the park signal)', () => {
        const pending = clarify({ call_reason: 'need scope', is_completed: false });
        expect(findPendingUserInput([pending], [])).toBe(pending);
    });

    it('returns null once every clarify is answered (resumed, not parked)', () => {
        const answered = clarify({ call_reason: 'need scope', is_completed: true });
        expect(findPendingUserInput([answered], [])).toBeNull();
    });

    it('prefers the NEWEST unanswered entry (latest park wins)', () => {
        const first = clarify({ call_reason: 'q1', is_completed: true });
        const second = clarify({ call_reason: 'q2', is_completed: false });
        expect(findPendingUserInput([first, second], [])).toBe(second);
    });

    it('collects clarifies from task history and legacy subtask children', () => {
        const taskClarify = clarify({ call_reason: 'task-level', is_completed: false });
        const childClarify = clarify({ call_reason: 'child-level', is_completed: false });
        // newest unanswered wins; child is appended after the task history, so it is later
        expect(
            findPendingUserInput([], [{ history: [taskClarify], children: [{ history: [childClarify] }] }]),
        ).toBe(childClarify);
    });

    it('tolerates null/undefined inputs and missing history', () => {
        expect(findPendingUserInput(null, null)).toBeNull();
        expect(findPendingUserInput(undefined, [{ history: null, children: null }])).toBeNull();
    });
});
