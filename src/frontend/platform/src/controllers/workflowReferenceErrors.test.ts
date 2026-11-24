import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import i18next from 'i18next';
import en from '../../public/locales/en-US/api_errors.json';
import zh from '../../public/locales/zh-Hans/api_errors.json';
import ja from '../../public/locales/ja/api_errors.json';
import request, { showApiError } from './request';

const notices = vi.hoisted(() => vi.fn());
vi.mock('@bisheng/ui', () => ({ notification: { open: notices } }));
const adapter = request.defaults.adapter;

beforeAll(async () => {
    await i18next.init({ lng: 'en', resources: {
        en: { api_errors: en }, 'zh-Hans': { api_errors: zh }, ja: { api_errors: ja },
    } });
});
afterEach(async () => {
    request.defaults.adapter = adapter;
    notices.mockClear();
    await i18next.changeLanguage('en');
});

function failure(resourceType: string, extra: Record<string, unknown> = {}) {
    return {
        status_code: 10996, status_message: 'PRIVATE /stack',
        data: {
            reason: resourceType.includes('model') ? 'model_selection_unavailable' : 'knowledge_reference_target_unavailable',
            exception: 'PRIVATE SQL',
            workflow_reference_errors: [{
                node_id: 'node-1', node_name: 'Search', resource_type: resourceType, target_id: '999', ...extra,
            }],
        },
    };
}

it.each(['en', 'zh-Hans', 'ja'])('shows localized resource and node details in %s', async language => {
    await i18next.changeLanguage(language);
    for (const type of ['model', 'rerank_model', 'knowledge_space', 'qa_knowledge']) {
        const error = showApiError(failure(type));
        expect(error.message).toBe(i18next.t(`api_errors:workflow_reference_${type}`, { nodeName: 'Search', targetId: '999' }));
        expect(error.message).toContain('Search');
        expect(error.message).toContain('999');
        expect(error.message).not.toContain('PRIVATE');
    }
});

it('retains the full API failure and displays its specific details once', async () => {
    const envelope = failure('knowledge_space');
    request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: envelope });
    const error = await request.patch('/api/v1/workflow/status', {}).catch(cause => cause);
    expect(error.status_code).toBe(10996);
    expect(error.data).toEqual(envelope.data);
    expect(error.message).toContain('knowledge space/library');
    showApiError(error);
    expect(notices).toHaveBeenCalledTimes(1);
    expect(notices).toHaveBeenCalledWith(expect.objectContaining({ description: error.message }));
});

it('keeps generic copy for older servers and malformed or unrelated diagnostics', () => {
    const older = { status_code: 10996, data: { reason: 'reference_target_invalid', exception: 'PRIVATE' } };
    const unknown = failure('model');
    unknown.data.reason = 'internal_error';
    for (const envelope of [older, unknown, failure('unknown'), failure('model', { target_id: '/private/path' }),
        failure('model', { node_name: {} }), failure('model', { node_name: 'x'.repeat(101) })]) {
        expect(showApiError(envelope).message).toBe(en['10996']);
    }
});

it('bounds and deduplicates the displayed locations', () => {
    const envelope = failure('model');
    const detail = envelope.data.workflow_reference_errors[0];
    envelope.data.workflow_reference_errors = Array.from({ length: 20 }, () => detail);
    expect(showApiError(envelope).message.split('\n')).toHaveLength(1);
});
