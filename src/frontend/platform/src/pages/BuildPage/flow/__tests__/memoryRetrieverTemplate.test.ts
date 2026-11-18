import { describe, expect, it } from 'vitest';
import { getWorkflowNodeTemplate } from '@/controllers/API/workflow';
import { Colors, Icons } from '../FlowNode/NodeLogo';
import zhHans from '../../../../../public/locales/zh-Hans/flow.json';
import enUS from '../../../../../public/locales/en-US/flow.json';
import ja from '../../../../../public/locales/ja/flow.json';

type Param = { key: string; type: string; value?: unknown; required?: boolean; min?: number; max?: number; label?: string; placeholder?: string; help?: string; global?: string };
type Group = { name?: string; params: Param[] };
type Template = { type: string; name: string; description: string; group_params: Group[] };

async function memoryTemplate(): Promise<Template> {
    const templates = (await getWorkflowNodeTemplate()) as Template[];
    const node = templates.find(item => item.type === 'memory_retriever');
    if (!node) throw new Error('memory_retriever template missing');
    return node;
}

function param(node: Template, key: string): Param {
    const found = node.group_params.flatMap(group => group.params).find(item => item.key === key);
    if (!found) throw new Error(`param ${key} missing`);
    return found;
}

function lookup(locale: unknown, path: string): unknown {
    return path.split('.').reduce<unknown>((value, segment) => (value && typeof value === 'object' ? (value as Record<string, unknown>)[segment] : undefined), locale);
}

describe('memory retriever node template', () => {
    it('AC-78: the node panel template offers a memory_retriever node', async () => {
        const node = await memoryTemplate();
        expect(node.name).toBe('true');
        expect(node.description).toBe('true');
        expect(Icons).toHaveProperty('memory_retriever');
        expect(Colors).toHaveProperty('memory_retriever');
    });

    it('AC-79: query is a required var_textarea that accepts text and variables', async () => {
        const query = param(await memoryTemplate(), 'query');
        expect(query.type).toBe('var_textarea');
        expect(query.required).toBe(true);
        expect(query.value).toBe('');
    });

    it('AC-79 AC-80: limit is a number control defaulting to 20 within 1-100, output is retrieved_memory', async () => {
        const node = await memoryTemplate();
        const limit = param(node, 'limit');
        expect(limit.type).toBe('number');
        expect(limit.value).toBe(20);
        expect(limit.min).toBe(1);
        expect(limit.max).toBe(100);
        const output = param(node, 'retrieved_memory');
        expect(output.type).toBe('var');
        expect(output.global).toBe('key');
    });

    it('AC-78 AC-79: every label the node renders exists in all three languages', async () => {
        const node = await memoryTemplate();
        const keys = ['name', 'description'];
        node.group_params.forEach(group => {
            if (group.name) keys.push(group.name);
            group.params.forEach(item => {
                (['label', 'placeholder', 'help'] as const).forEach(field => {
                    if (item[field]) keys.push(`${item.key}.${field}`);
                });
            });
        });
        for (const locale of [zhHans, enUS, ja]) {
            for (const key of keys) {
                const value = lookup(locale, `node.memory_retriever.${key}`);
                expect(typeof value, `node.memory_retriever.${key}`).toBe('string');
                expect(String(value).length).toBeGreaterThan(0);
            }
        }
    });
});
