import { describe, expect, it } from 'vitest';
import { MEMORY_SWITCH_DEFAULT, MEMORY_SWITCH_KEY, applyNewWorkflowMemorySwitch, findNodeParam } from '@/util/workflowMemory';

type Param = { key: string; value?: unknown };
type Node = { data: { type: string; group_params: { name?: string; params: Param[] }[] } };

const start = (params: Param[] = []): Node => ({ data: { type: 'start', group_params: [{ name: 'basic', params }] } });
const switchValue = (node: Node) => findNodeParam(node.data, MEMORY_SWITCH_KEY)?.value;

describe('workflow created from a template (AC-75)', () => {
    it('gives a template saved before the switch existed the new-workflow default', () => {
        const node = start();
        applyNewWorkflowMemorySwitch([node, { data: { type: 'end', group_params: [] } }]);
        expect(switchValue(node)).toBe(MEMORY_SWITCH_DEFAULT);
    });

    it('applies the new-workflow default over a template saved with the switch off', () => {
        const node = start([{ key: MEMORY_SWITCH_KEY, value: false }]);
        applyNewWorkflowMemorySwitch([node]);
        expect(switchValue(node)).toBe(MEMORY_SWITCH_DEFAULT);
    });

    it('keeps a template that turned memory on switched on', () => {
        const node = start([{ key: MEMORY_SWITCH_KEY, value: true }]);
        applyNewWorkflowMemorySwitch([node]);
        expect(switchValue(node)).toBe(true);
    });

    it('leaves graphs without a start node alone', () => {
        const nodes = [{ data: { type: 'end', group_params: [] } }];
        applyNewWorkflowMemorySwitch(nodes);
        expect(nodes[0].data.group_params).toEqual([]);
    });
});
