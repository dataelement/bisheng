import { normalizeApiError } from '@bisheng/api-client';
import request from './request';
import { findPersonalSkillByImport } from './skillCenter';
jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));

it('recovers only the named not-imported result after strict rejection', async () => {
  const missing = normalizeApiError({ status_code: 11053 }, { message: 'not imported' });
  (request.get as jest.Mock).mockRejectedValueOnce(missing);
  await expect(findPersonalSkillByImport('new-import')).resolves.toBeNull();
  const conflict = normalizeApiError({ status_code: 11055 }, { message: 'duplicate' });
  (request.get as jest.Mock).mockRejectedValueOnce(conflict);
  await expect(findPersonalSkillByImport('another-import')).rejects.toBe(conflict);
});
