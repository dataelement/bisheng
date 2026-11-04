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
    expect(availableModelTypes(provider)).toContain('asr_rt');
    expect(availableModelTypes(provider)).not.toContain('asr');
    expect(availableModelTypes(provider)).not.toContain('tts');
});

it('keeps file ASR on OpenAI and both speech types on Qwen', () => {
    expect(availableModelTypes('openai')).toContain('asr');
    expect(availableModelTypes('openai')).not.toContain('asr_rt');
    expect(availableModelTypes('qwen')).toEqual(expect.arrayContaining(['asr', 'asr_rt']));
});

it('imports a confirmed speech row only after a type is chosen', () => {
    const speech: DiscoveredModel = {
        model_name: 'paraformer-v2',
        display_name: 'Paraformer',
        model_type: null,
        type_source: 'speech',
    };
    expect(importableModels([speech], new Set(['paraformer-v2']), {}, [], 'qwen')).toEqual([]);
    expect(importableModels([speech], new Set(['paraformer-v2']), { 'paraformer-v2': 'asr_rt' }, [], 'qwen')
        .map(model => model.model_type)).toEqual(['asr_rt']);
});
