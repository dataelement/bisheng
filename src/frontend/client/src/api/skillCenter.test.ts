import request from './request';
import { getCenterSkills } from './skillCenter';

jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));

test('the API adapter retains builtin provenance and separates personal skills', async () => {
  const row = { id: 1, name: 'bisheng-docx', display_name: 'Configured title', description: 'Configured description',
    enabled: true, content_hash: 'revision', updated_at: '2026-10-30' };
  jest.mocked(request.get).mockResolvedValue({ status_code: 200, data: [
    { ...row, source: 'platform', builtin_key: 'bisheng-docx' },
    { ...row, id: 2, source: 'platform', builtin_key: null },
    { ...row, id: 3, source: 'platform' },
    { ...row, id: 4, source: 'personal', builtin_key: 'bisheng-docx', instructions: 'Personal body' },
  ] });
  const skills = await getCenterSkills();
  expect(skills[0]).toMatchObject({ source: 'platform', builtinKey: 'bisheng-docx', displayName: row.display_name });
  expect(skills[1]).toMatchObject({ source: 'platform', builtinKey: null });
  expect(skills[2]).toMatchObject({ source: 'platform', builtinKey: undefined });
  expect(skills[3]).toMatchObject({ source: 'personal', instructions: 'Personal body', displayName: row.display_name });
  expect(skills[3]).not.toHaveProperty('builtinKey');
});
