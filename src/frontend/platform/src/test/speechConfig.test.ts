import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import { asrProviders, ttsProviders, configWithDefaults, getConfigError, getSpeechFields } from '../pages/ModelPage/manage/speechConfig';
import { getModelProviders } from '../pages/ModelPage/manage/modelProviderFields';

const t = ((key: string) => key) as TFunction;

describe('native speech provider configuration', () => {
    it('offers ASR for the added providers while preserving TTS capabilities', () => {
        expect(asrProviders).toEqual(['openai', 'azure_openai', 'qwen', 'volcengine', 'qianfan', 'tencent']);
        expect(ttsProviders).toEqual(['openai', 'azure_openai', 'qwen', 'qianfan']);
    });
    it('requires speech credentials independently of LLM keys', () => {
        for (const provider of ['volcengine', 'qianfan', 'tencent']) {
            const fields = getSpeechFields(provider, {}, t);
            const config = configWithDefaults({ api_key: 'llm-key' }, fields, false);
            expect(getConfigError(config, fields)).not.toBe('');
            expect(config.api_key).toBe('llm-key');
        }
    });
    it('selects exactly one Volcengine authentication mode and a resource ID', () => {
        const current = getSpeechFields('volcengine', {}, t);
        const legacy = getSpeechFields('volcengine', { speech_auth_mode: 'app_key' }, t);
        expect(current.map(field => field.key)).toEqual(['speech_auth_mode', 'speech_api_key', 'speech_resource_id']);
        expect(legacy.map(field => field.key)).toEqual(['speech_auth_mode', 'speech_app_id', 'speech_access_key', 'speech_resource_id']);
        const config = configWithDefaults({ speech_api_key: 'key' }, current, false);
        expect(config.speech_resource_id).toBe('volc.seedasr.sauc.duration');
        expect(getConfigError(config, current)).toBe('');
    });
    it('preserves masked secrets and hidden provider settings on edit', () => {
        const stored = { api_key: '********', base_url: 'https://qianfan.baidubce.com/v2', speech_app_id: '123', speech_api_key: '********' };
        const values = configWithDefaults(stored, getSpeechFields('qianfan', stored, t), false);
        expect(values).toEqual(stored);
        expect(getConfigError(values, getSpeechFields('qianfan', stored, t))).toBe('');
    });
    it('retains existing provider defaults and rejects whitespace credentials', () => {
        const fields = getModelProviders().qwen;
        const config = configWithDefaults({ openai_api_key: '  ' }, fields, true);
        expect(config.openai_api_base).toBe('https://dashscope.aliyuncs.com/compatible-mode/v1');
        expect(getConfigError(config, fields)).toBe('API Key');
        expect(getSpeechFields('tencent', {}, t).map(field => field.key)).toEqual(['speech_app_id', 'speech_secret_id', 'speech_secret_key']);
    });
});
