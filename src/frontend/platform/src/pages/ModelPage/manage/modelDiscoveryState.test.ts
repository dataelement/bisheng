import { describe, expect, it } from 'vitest';
import { DiscoveredModel } from '@/controllers/API/modelDiscovery';
import { availableModelTypes, importableModels } from './modelDiscoveryState';

const models: DiscoveredModel[] = [
    { model_name: 'gpt-4o', display_name: 'GPT', model_type: 'llm', type_source: 'registry' },
    { model_name: 'whisper-1', display_name: 'Whisper', model_type: 'asr', type_source: 'registry' },
    { model_name: 'private', display_name: 'Private', model_type: null, type_source: 'unknown' },
    { model_name: 'image', display_name: 'Image', model_type: null, type_source: 'unsupported' },
];
describe('catalog import', () => {
    it('keeps existing models and requires confirmation of unknown types', () => {
        const selected = new Set(models.map(model => model.model_name));
        expect(importableModels(models, selected, {}, [' gpt-4o '], 'openai').map(model => model.model_name)).toEqual(['whisper-1']);
        expect(importableModels(models, selected, { private: 'embedding', image: 'llm' }, ['gpt-4o'], 'openai').map(model => model.model_type)).toEqual(['asr', 'embedding']);
    });
    it('filters unselected and unsupported provider types', () => {
        expect(importableModels(models, new Set(['whisper-1', 'private']), { private: 'llm' }, [], 'vllm').map(model => model.model_name)).toEqual(['private']);
    });
});

it.each(['volcengine', 'tencent'])('uses the current ASR adapter boundary for %s', provider => {
    expect(availableModelTypes(provider)).toContain('asr');
    expect(availableModelTypes(provider)).not.toContain('tts');
});
