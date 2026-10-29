import i18next from 'i18next';
import catalog from '../../../packages/locales/src/api_errors/en.json';
import { extractKnowledgeFileError, getSpaceChildrenApi } from './knowledge';
import request from './request';
jest.mock('~/api/request', () => ({ __esModule: true, default: { get: jest.fn() } }));
beforeAll(async () => { await i18next.init({ lng: 'en', resources: { en: { translation: { api_errors: catalog } } } }); });
it.each([{ error_message: 'PRIVATE stack' }, { remark: 'PRIVATE SQL' }, { remark: JSON.stringify({ data: { exception: 'PRIVATE' } }) }, { remark: JSON.stringify({ status_code: 49999, status_message: 'PRIVATE' }) }])('does not expose unknown parse evidence: %p', raw => {
 expect(extractKnowledgeFileError(raw)).not.toContain('PRIVATE');
});
it('retains registered business context without technical exceptions', () => {
 expect(extractKnowledgeFileError({ remark: JSON.stringify({ status_code: 10019, data: { exception: 'PRIVATE' } }) })).toBe(catalog['10019']);
});

it('does not label rename metadata as a parse failure', () => {
 expect(extractKnowledgeFileError({ remark: JSON.stringify({ old_name: 'old.txt', new_name: 'new.txt' }) })).toBeUndefined();
});

it('retains original parse evidence separately from the mapped user message', async () => {
 const remark = { status_code: 49999, data: { exception: 'PRIVATE' } };
 const row = { id: 1, name: 'a.txt', type: 'file', status: 'FAILED', remark, error_message: 'PRIVATE stack' };
 (request.get as jest.Mock).mockResolvedValueOnce({ data: { data: [row], has_more: false } });
 const result = await getSpaceChildrenApi({ space_id: '1' });
 expect(result.data[0].errorMessage).toBe(catalog.fallback);
 expect(result.data[0].failureEvidence?.remark).toBe(remark);
 expect(result.data[0].failureEvidence?.errorMessage).toBe(row.error_message);
 expect(result.data[0]._raw).toBeUndefined();
});
