import type { TFunction } from 'i18next';

export interface ConfigField {
    label: string;
    key: string;
    type: string;
    required: boolean;
    default: string;
    placeholder?: string;
    example?: string;
    options?: { value: string; label: string }[];
}
export type ProviderConfig = Record<string, string>;
export const speechProviders = ['volcengine', 'qianfan', 'tencent'];
export const asrProviders = ['openai', 'azure_openai', 'qwen', ...speechProviders];
export const ttsProviders = ['openai', 'azure_openai', 'qwen', 'qianfan'];
export const speechDocs: Record<string, string> = {
    volcengine: 'https://docs.volcengine.com/docs/DoubaoVoice/LargemodelstreamingautomaticspeechrecognitionAPI?lang=zh',
    qianfan: 'https://ai.baidu.com/ai-doc/SPEECH/jlbxejt2i',
    tencent: 'https://cloud.tencent.com/document/product/1093/48982',
};
export const asrHints: Record<string, string> = {
    qwen: 'model.streamingAsrHint', volcengine: 'model.volcAsrHint',
    qianfan: 'model.baiduAsrHint', tencent: 'model.tencentAsrHint',
};

export function getSpeechFields(provider: string, config: ProviderConfig, t: TFunction): ConfigField[] {
    const field = (key: string, label: string, type = 'text', defaultValue = ''): ConfigField =>
        ({ key, label, type, required: true, default: defaultValue });
    const app = field('speech_app_id', 'AppID');
    const api = field('speech_api_key', 'API Key', 'password');
    if (provider === 'qianfan') return [app, api];
    if (provider === 'tencent') return [app, field('speech_secret_id', 'SecretId'), field('speech_secret_key', 'SecretKey', 'password')];
    if (provider !== 'volcengine') return [];
    const mode = config.speech_auth_mode || 'api_key';
    const resourceIds = [
        'volc.seedasr.sauc.duration', 'volc.seedasr.sauc.concurrent',
        'volc.bigasr.sauc.duration', 'volc.bigasr.sauc.concurrent',
    ];
    return [
        { ...field('speech_auth_mode', t('model.speechAuthMode'), 'select', 'api_key'), options: [
            { value: 'api_key', label: 'API Key' },
            { value: 'app_key', label: 'AppID + Access Token' },
        ] },
        ...(mode === 'app_key' ? [app, field('speech_access_key', 'Access Token', 'password')] : [api]),
        { ...field('speech_resource_id', 'Resource ID', 'select', resourceIds[0]),
            options: resourceIds.map(value => ({ value, label: value })) },
    ];
}

export function configWithDefaults(config: ProviderConfig, fields: ConfigField[], showDefault: boolean): ProviderConfig {
    const result = { ...config };
    for (const field of fields) {
        if (result[field.key] === undefined && (showDefault || field.key.startsWith('speech_'))) {
            result[field.key] = field.default;
        }
    }
    return result;
}

export function getConfigError(config: ProviderConfig, fields: ConfigField[]): string {
    return fields.find(field => field.required && !config[field.key]?.trim())?.label || '';
}
