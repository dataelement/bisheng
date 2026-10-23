import { describe, expect, it } from 'vitest';

import {
    filterModelOption,
    fromModelCascaderValue,
    toGroupedModelOptions,
    toModelCascaderOptions,
    toModelCascaderValue,
    toModelSelectValue,
    type ModelProviderNode,
} from './modelOptions';

const modelTree: ModelProviderNode[] = [
    {
        value: 10,
        label: 'Provider A',
        children: [
            { value: 101, label: 'Model 101' },
            { value: '', label: 'Invalid model' },
        ],
    },
    {
        value: 'provider-b',
        label: 'Provider B',
        children: [{ value: 'model-b', label: 'Model B' }],
    },
    { value: 'empty-provider', label: 'Empty provider', children: [] },
];

describe('model cascader options', () => {
    it('keeps providers as parents, removes invalid rows, and normalizes ids', () => {
        expect(toModelCascaderOptions(modelTree)).toEqual([
            {
                value: '10',
                label: 'Provider A',
                children: [{ value: '101', label: 'Model 101' }],
            },
            {
                value: 'provider-b',
                label: 'Provider B',
                children: [{ value: 'model-b', label: 'Model B' }],
            },
        ]);
    });

    it('resolves stored model ids to controlled paths', () => {
        expect(toModelCascaderValue(101, modelTree)).toEqual(['10', '101']);
        expect(toModelCascaderValue('model-b', modelTree)).toEqual(['provider-b', 'model-b']);
        expect(toModelCascaderValue('missing', modelTree)).toBeNull();
        expect(toModelCascaderValue('', modelTree)).toBeNull();
    });

    it('returns only the leaf id for the existing API payload', () => {
        expect(fromModelCascaderValue(['provider-b', 'model-b'])).toBe('model-b');
        expect(fromModelCascaderValue(null)).toBeNull();
    });
});

describe('model select options', () => {
    it('flattens providers into grouped rows and drops invalid models', () => {
        expect(toGroupedModelOptions(modelTree)).toEqual([
            { value: '101', label: 'Model 101', group: 'Provider A' },
            { value: 'model-b', label: 'Model B', group: 'Provider B' },
        ]);
        expect(toGroupedModelOptions(undefined)).toEqual([]);
    });

    it('stringifies a stored model id and leaves an empty value unselected', () => {
        expect(toModelSelectValue(101)).toBe('101');
        expect(toModelSelectValue('model-b')).toBe('model-b');
        expect(toModelSelectValue('')).toBeNull();
        expect(toModelSelectValue(null)).toBeNull();
    });

    it('matches the model name or the provider name', () => {
        const option = { value: '101', label: 'Model 101', group: 'Provider A' };
        expect(filterModelOption('101', option)).toBe(true);
        expect(filterModelOption('provider', option)).toBe(true);
        expect(filterModelOption('missing', option)).toBe(false);
        expect(filterModelOption('  ', option)).toBe(true);
    });
});
