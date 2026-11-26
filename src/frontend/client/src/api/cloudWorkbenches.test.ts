import request from './request';
import { getCloudWorkbenches } from './cloudWorkbenches';
jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));

test('unwraps the API envelope instead of treating it as a catalog', async () => {
  const page = { items: [{ id: 'board', name: 'Board', description: '', entry_url: 'https://enterprise.test/apps/board/' }], next_cursor: null };
  jest.mocked(request.get).mockResolvedValueOnce({ status_code: 200, data: page });
  expect(await getCloudWorkbenches()).toEqual(page);
});

test('rejects business refusals and malformed lists instead of showing empty success', async () => {
  for (const response of [{ status_code: 403, data: { items: [] } }, { status_code: 200, data: {} }]) {
    jest.mocked(request.get).mockResolvedValueOnce(response);
    await expect(getCloudWorkbenches()).rejects.toThrow('unavailable');
  }
});
