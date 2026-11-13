/* eslint-disable no-restricted-syntax -- CJK fixtures assert the zh-Hans AC-75 explanation wording. */
import { cleanup, render, renderHook, screen } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { getWorkflowNodeTemplate } from '@/controllers/API/workflow';
import { flowVersionCompatible } from '@/util/flowCompatible';
import SwitchItem from '../FlowNode/component/SwitchItem';
import { MEMORY_LIMIT_MAX, MEMORY_LIMIT_MIN, useNodeEvent, validateMemoryLimits } from '../hooks/useNodeEvent';
import zhHans from '../../../../../public/locales/zh-Hans/flow.json';
import enUS from '../../../../../public/locales/en-US/flow.json';
import ja from '../../../../../public/locales/ja/flow.json';

type Param = { key: string; type: string; value?: unknown; desc?: string };
type Group = { name?: string; params: Param[] };
type NodeData = { id: string; name: string; type: string; description: string; v?: string | number; group_params: Group[] };

const translate = (key: string, options?: Record<string, unknown>) => (options ? `${key}:${JSON.stringify(options)}` : key);

async function template(type: string): Promise<NodeData> {
    const all = (await getWorkflowNodeTemplate()) as NodeData[];
    const found = all.find(item => item.type === type);
    if (!found) throw new Error(`${type} template missing`);
    return JSON.parse(JSON.stringify(found)) as NodeData;
}

function findParam(node: NodeData, key: string): Param | undefined {
    return node.group_params.flatMap(group => group.params).find(item => item.key === key);
}

type ValidationFlow = Parameters<typeof useNodeEvent>[0];

async function graph(options: { switchOn: boolean; limit?: unknown }): Promise<ValidationFlow> {
    const start = { ...(await template('start')), id: 'start_1' };
    const memory = { ...(await template('memory_retriever')), id: 'memory_retriever_1', name: 'Memory' };
    findParam(start, 'memory_enabled')!.value = options.switchOn;
    if (options.limit !== undefined) findParam(memory, 'limit')!.value = options.limit;
    const end = { id: 'end_1', name: 'end', type: 'end', description: '', group_params: [] };
    return {
        nodes: [start, memory, end].map(data => ({ id: data.id, type: 'flowNode', data })),
        edges: [{ source: 'start_1', target: 'memory_retriever_1' }, { source: 'memory_retriever_1', target: 'end_1' }],
    } as unknown as ValidationFlow;
}

afterEach(cleanup);

describe('workflow memory switch', () => {
    it('AC-70: the start node has a memory group whose memory_enabled switch defaults to off', async () => {
        const start = await template('start');
        const group = start.group_params.find(item => item.params.some(param => param.key === 'memory_enabled'));
        expect(group?.name).toBe('memory');
        const param = findParam(start, 'memory_enabled')!;
        expect(param.type).toBe('switch');
        expect(param.value).toBe(false);
        expect(param.desc).toBe('true');
    });

    it('AC-70: existing start nodes without the switch get it, off, when the workflow is opened', async () => {
        const start = await template('start');
        start.group_params = start.group_params.filter(group => group.name !== 'memory');
        const flow = flowVersionCompatible({ nodes: [{ id: 'start_1', data: start }], edges: [] });
        const params = flow.nodes[0].data.group_params.flatMap((group: Group) => group.params).filter((item: Param) => item.key === 'memory_enabled');
        expect(params).toHaveLength(1);
        expect(params[0].value).toBe(false);
        const again = flowVersionCompatible(flow);
        expect(again.nodes[0].data.group_params.flatMap((group: Group) => group.params).filter((item: Param) => item.key === 'memory_enabled')).toHaveLength(1);
    });

    it('AC-75: the switch shows the explanation next to it in all three languages', () => {
        render(createElement(SwitchItem, { data: { key: 'memory_enabled', value: false, label: 'true', desc: 'true' }, onChange: () => undefined, i18nPrefix: 'node.start.memory_enabled.' }));
        expect(screen.getByText('node.start.memory_enabled.desc')).toBeInTheDocument();
        expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
        const zhDesc = zhHans.node.start.memory_enabled.desc;
        expect(zhDesc).toContain('对话要点会整理进自己的记忆');
        expect(zhDesc).toContain('回答和输出');
        expect(zhDesc).toContain('其他用户看不到');
        for (const locale of [zhHans, enUS, ja]) {
            expect(locale.node.start.memory.length).toBeGreaterThan(0);
            expect(locale.node.start.memory_enabled.label.length).toBeGreaterThan(0);
            expect(locale.node.start.memory_enabled.desc.length).toBeGreaterThan(0);
            expect(locale.memoryLimitInvalid).toContain('{{min}}');
            expect(locale.memoryLimitInvalid).toContain('{{max}}');
            expect(locale.memoryRetrieverNeedsSwitch.length).toBeGreaterThan(0);
        }
    });
});

describe('memory retriever validation', () => {
    it.each([0, 101, 1.5, '', 'abc'])('AC-80: limit %p fails save validation with the legal range', async limit => {
        const flow = await graph({ switchOn: true, limit });
        const errors = validateMemoryLimits(flow.nodes, translate);
        expect(errors).toHaveLength(1);
        expect(errors[0]).toContain('memoryLimitInvalid');
        expect(errors[0]).toContain(`"min":${MEMORY_LIMIT_MIN}`);
        expect(errors[0]).toContain(`"max":${MEMORY_LIMIT_MAX}`);
        expect(errors[0]).toContain('Memory');
    });

    it.each([1, 20, 100, '50'])('AC-80: limit %p passes', async limit => {
        const flow = await graph({ switchOn: true, limit });
        expect(validateMemoryLimits(flow.nodes, translate)).toEqual([]);
    });

    it('AC-80: the run and publish check rejects an invalid limit', async () => {
        const flow = await graph({ switchOn: true, limit: 0 });
        const { result } = renderHook(() => useNodeEvent(flow));
        await expect(result.current()).resolves.toEqual(['memoryLimitInvalid']);
    });

    it('AC-85: publishing is rejected while the node exists and the switch is off', async () => {
        const flow = await graph({ switchOn: false });
        const { result } = renderHook(() => useNodeEvent(flow));
        await expect(result.current({ publish: true })).resolves.toEqual(['memoryRetrieverNeedsSwitch']);
    });

    it('AC-85: publishing passes once the switch is on; a debug run is not blocked by the switch', async () => {
        const on = await graph({ switchOn: true });
        const { result: published } = renderHook(() => useNodeEvent(on));
        await expect(published.current({ publish: true })).resolves.toEqual([]);
        const off = await graph({ switchOn: false });
        const { result: run } = renderHook(() => useNodeEvent(off));
        await expect(run.current()).resolves.toEqual([]);
    });
});
