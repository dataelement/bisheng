import request from './request';
import { getSkillCenter } from './skillCenter';

jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));

test('the center API adapter retains builtin provenance only for enterprise skills', async () => {
  const row = { id: 1, name: 'bisheng-docx', display_name: 'Configured title', description: 'Configured description',
    enabled: true, content_hash: 'revision', update_time: '2026-10-30', bundle_missing: false };
  jest.mocked(request.get).mockResolvedValue({ status_code: 200, data: {
    enterprise: [
      { ...row, builtin_key: 'bisheng-docx' },
      { ...row, id: 2, builtin_key: null },
      { ...row, id: 3 },
    ],
    personal: [{ ...row, id: 4, builtin_key: 'bisheng-docx' }],
    personal_count: 1, enterprise_count: 3,
  } });
  const skills = await getSkillCenter();
  expect(skills.enterprise[0]).toMatchObject({ source: 'platform', builtinKey: 'bisheng-docx', displayName: row.display_name });
  expect(skills.enterprise[1]).toMatchObject({ source: 'platform', builtinKey: null });
  expect(skills.enterprise[2]).toMatchObject({ source: 'platform', builtinKey: undefined });
  expect(skills.personal[0]).toMatchObject({ source: 'personal', id: 4, displayName: row.display_name });
  expect(skills.personal[0]).not.toHaveProperty('builtinKey');
});
