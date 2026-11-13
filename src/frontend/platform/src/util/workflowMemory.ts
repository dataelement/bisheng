// F132 long-term memory: workflow-side constants and checks shared by the node
// template, the legacy-flow upgrade and the save / publish validation.

export const MEMORY_RETRIEVER_NODE_TYPE = 'memory_retriever';
export const MEMORY_SWITCH_KEY = 'memory_enabled';
export const MEMORY_START_GROUP_NAME = 'memory';
export const MEMORY_LIMIT_MIN = 1;
export const MEMORY_LIMIT_MAX = 100;

interface MemoryParam {
    key: string;
    value?: unknown;
}

interface MemoryGroup {
    name?: string;
    params?: MemoryParam[];
}

interface MemoryNodeData {
    id?: string;
    name?: string;
    type?: string;
    group_params?: MemoryGroup[] | null;
}

/** The start node's "memory" group with the workflow memory switch, default off (AC-70, AC-75). */
export function createMemoryStartGroup() {
    return {
        name: MEMORY_START_GROUP_NAME,
        params: [
            {
                key: MEMORY_SWITCH_KEY,
                label: 'true',
                type: 'switch',
                value: false,
                desc: 'true',
            },
        ],
    };
}

export function findNodeParam(node: MemoryNodeData | undefined, key: string): MemoryParam | undefined {
    for (const group of node?.group_params ?? []) {
        const found = (group.params ?? []).find(param => param.key === key);
        if (found) return found;
    }
    return undefined;
}

/** Adds the memory group to a start node saved before the switch existed. */
export function ensureMemoryStartGroup(node: MemoryNodeData) {
    if (!Array.isArray(node.group_params)) return;
    if (findNodeParam(node, MEMORY_SWITCH_KEY)) return;
    node.group_params.push(createMemoryStartGroup());
}

/** A limit is valid only as an integer from 1 to 100 (AC-80); numeric strings count. */
export function isValidMemoryLimit(value: unknown): boolean {
    if (typeof value === 'string' && !/^\d+$/.test(value.trim())) return false;
    if (typeof value !== 'string' && typeof value !== 'number') return false;
    const limit = Number(value);
    return Number.isInteger(limit) && limit >= MEMORY_LIMIT_MIN && limit <= MEMORY_LIMIT_MAX;
}

/** Retriever nodes whose limit is out of range. */
export function invalidMemoryLimitNodes<T extends MemoryNodeData>(nodes: T[]): T[] {
    return nodes.filter(node => node.type === MEMORY_RETRIEVER_NODE_TYPE && !isValidMemoryLimit(findNodeParam(node, 'limit')?.value));
}

/** Retriever nodes that cannot work because the start node switch is off (AC-85). */
export function memoryRetrieversWithSwitchOff<T extends MemoryNodeData>(nodes: T[]): T[] {
    const retrievers = nodes.filter(node => node.type === MEMORY_RETRIEVER_NODE_TYPE);
    if (!retrievers.length) return [];
    const start = nodes.find(node => node.type === 'start');
    return findNodeParam(start, MEMORY_SWITCH_KEY)?.value === true ? [] : retrievers;
}
