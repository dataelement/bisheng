import { describe, expect, it } from 'vitest';
import { referenceErrorMessage } from './referenceErrors';
import { referenceReasonGroups } from './referenceReasons';
import en from '../../locales/src/api_errors/en.json';
import zh from '../../locales/src/api_errors/zh-Hans.json';
import ja from '../../locales/src/api_errors/ja.json';

const translate = (locale: Record<string, string>) => (key: string, values: Record<string, string> = {}) =>
    locale[key]?.replace(/{{(\w+)}}/g, (_, name: string) => values[name] ?? '') ?? key;
const failure = (state = 'invalid_missing', extra: Record<string, unknown> = {}) => ({
    status_code: 10996, status_message: 'PRIVATE stack',
    data: { reason: 'reference_target_invalid', exception: 'PRIVATE SQL', reference_errors: [{
        node_id: 'llm_b1ef4', node_name: 'LLM', resource_type: 'model', target_id: '375', state, ...extra,
    }] },
});

describe.each([en, zh, ja])('localized reference diagnostics', locale => {
    const t = translate(locale);
    it('reports the node, selected model ID and exact missing cause', () => {
        const message = referenceErrorMessage(failure(), t);
        expect(message).toBe(t('reference_state_invalid_missing', { location: t('reference_node_with_id', { nodeName: 'LLM', nodeId: 'llm_b1ef4' }), resource: t('reference_resource_model'), targetId: '375' }));
        expect(message).toContain('LLM');
        expect(message).toContain('375');
        expect(message).not.toContain('PRIVATE');
        expect(message).not.toContain('{{');
    });
    it('distinguishes absent, deleted, deleting, foreign, offline and incompatible targets', () => {
        const messages = ['invalid_missing', 'invalid_legacy', 'invalid_deleted', 'deleting', 'invalid_scope', 'offline', 'type_mismatch', 'unavailable']
            .map(state => referenceErrorMessage(failure(state), t));
        expect(new Set(messages).size).toBe(8);
    });
    it('localizes every known reason without exposing raw protocol or diagnostic text', () => {
        for (const [group, reasons] of Object.entries(referenceReasonGroups)) {
            expect(locale).toHaveProperty(`reference_reason_${group}`);
            for (const reason of reasons) {
                const message = referenceErrorMessage({ status_code: 10996, data: { reason, exception: 'PRIVATE' } }, t);
                expect(message).toBe(t(`reference_reason_${group}`));
                expect(message).not.toContain('PRIVATE');
                expect(message).not.toContain(reason);
            }
        }
    });
});

it('keeps exact causes for resources without workflow nodes', () => {
    const envelope = failure('invalid_deleted', { resource_type: 'knowledge_file', node_name: undefined });
    expect(referenceErrorMessage(envelope, translate(en))).toContain('knowledge file (ID: 375) has been deleted');
});

it('rejects untrusted fields and unknown diagnostics while keeping an actionable known reason', () => {
    for (const extra of [{ node_name: {} }, { node_name: 'x'.repeat(101) }, { target_id: 'PRIVATE/path' }, { resource_type: 'PRIVATE' }, { state: 'PRIVATE' }]) {
        expect(referenceErrorMessage(failure('invalid_missing', extra), translate(en))).toBe(en.reference_reason_reference_target_invalid);
    }
    expect(referenceErrorMessage({ status_code: 10996, data: { ...failure().data, reason: 'PRIVATE' } }, translate(en))).toBe('');
    expect(referenceErrorMessage({ ...failure(), status_code: 500 }, translate(en))).toBe('');
});

it('deduplicates and bounds details', () => {
    const envelope = failure();
    envelope.data.reference_errors = Array.from({ length: 12 }, () => envelope.data.reference_errors[0]);
    expect(referenceErrorMessage(envelope, translate(en)).split('\n')).toHaveLength(1);
    envelope.data.reference_errors = Array.from({ length: 12 }, (_, index) => ({ ...envelope.data.reference_errors[0], node_name: `Node ${index}` }));
    expect(referenceErrorMessage(envelope, translate(en)).split('\n')).toHaveLength(5);
});


it('uses caller fallback until translations are initialized', () => {
    expect(referenceErrorMessage(failure(), key => `api_errors.${key}`)).toBe('');
    expect(referenceErrorMessage(failure(), () => undefined as never)).toBe('');
});

it('identifies the missing model in the reported 116 workflow', () => {
    // eslint-disable-next-line no-restricted-syntax -- Verify the reported node label as a test fixture, not UI copy.
    expect(referenceErrorMessage(failure('invalid_missing', { node_name: '大模型' }), translate(zh))).toBe(
        // eslint-disable-next-line no-restricted-syntax -- Assert the exact localized regression output.
        '节点“大模型”（llm_b1ef4）引用的模型（ID：375）不存在，请在应用配置中重新选择后保存或发布。',
    );
});
