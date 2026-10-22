import { describe, expect, it } from 'vitest';

import {
    fromModelCascaderValue,
    toModelCascaderOptions,
    toModelCascaderValue,
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
