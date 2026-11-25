import { beforeAll, expect, it } from 'vitest';
import i18next from 'i18next';
import catalog from '../../../public/locales/en-US/api_errors.json';
import { resolveKnowledgeParseFailure } from './knowledgeParseFailureMessage';
beforeAll(async () => { await i18next.init({ lng: 'en', resources: { en: { api_errors: catalog } } }); });
const t = (key: string, options?: Record<string, unknown>) => String(i18next.t(key, options ?? {}));
it.each(['private SQL', { message: 'private stack' }, { status_code: 49999, status_message: 'secret' }])('does not return unregistered parser evidence: %p', remark => {
 expect(resolveKnowledgeParseFailure(remark, t)).toBeUndefined();
});
it('explains a generic file parse failure and does not use the operation fallback', () => {
 const message = resolveKnowledgeParseFailure({ code: 10953 }, t);
 expect(message).toBe(catalog['10953']);
 expect(message).toMatch(/process it again/i);
 expect(message).not.toBe(catalog.fallback);
 expect(message).not.toContain('exception');
});
it('retains specific known messages without diagnostic interpolation', () => {
 const message = resolveKnowledgeParseFailure({ status_code: 10019, data: { exception: 'SECRET' } }, t);
 expect(message).toBe(catalog['10019']); expect(message).not.toContain('SECRET');
});


it('shows the missing referenced knowledge file instead of a generic parse failure', () => {
 const message = resolveKnowledgeParseFailure({ code: 10996, data: {
  reason: 'reference_target_invalid', exception: 'PRIVATE', reference_errors: [{ resource_type: 'knowledge_file', target_id: '17', state: 'invalid_deleted' }],
 } }, t);
 expect(message).toContain('knowledge file (ID: 17) has been deleted');
 expect(message).not.toContain('PRIVATE');
});
