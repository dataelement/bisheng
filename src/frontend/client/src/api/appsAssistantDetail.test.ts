/** @jest-environment node */

import { getAssistantDetailApi } from './apps';
import request from './request';

jest.mock('./request', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));
jest.mock('~/utils', () => ({ generateUUID: jest.fn() }));

const mockedGet = jest.mocked(request.get);

describe('assistant detail description', () => {
  it.each(['v1', 'v2'])('exposes the saved description to %s conversation consumers', async (version) => {
    const response = {
      status_code: 200,
      data: { id: 'assistant-28', name: 'Acceptance assistant', desc: 'Saved application summary', can_share: true },
    };
    mockedGet.mockResolvedValue(response);

    const result = await getAssistantDetailApi('assistant-28', 'share-token', true, version);

    expect(result.data.description).toBe('Saved application summary');
    expect(result.data).toMatchObject(response.data);
    expect(mockedGet).toHaveBeenCalledWith(`/api/${version}/assistant/info/assistant-28`, {
      headers: { 'share-token': 'share-token' },
      skip403Redirect: true,
    });
  });

  it('reflects an explicitly cleared saved description', async () => {
    mockedGet.mockResolvedValue({ status_code: 200, data: { desc: '', description: 'Previous summary' } });
    expect((await getAssistantDetailApi('assistant-28')).data.description).toBe('');
  });

  it('preserves an already normalized description', async () => {
    mockedGet.mockResolvedValue({ status_code: 200, data: { description: 'Normalized summary' } });
    expect((await getAssistantDetailApi('assistant-28')).data.description).toBe('Normalized summary');
  });

  it.each([null, {}])('represents an empty saved description as an empty string (%j)', async (data) => {
    mockedGet.mockResolvedValue({ status_code: 200, data: data ?? { desc: null } });
    expect((await getAssistantDetailApi('assistant-28')).data.description).toBe('');
  });

  it('preserves failure responses for the existing error handling', async () => {
    const response = { status_code: 403, status_message: 'Access denied', data: null };
    mockedGet.mockResolvedValue(response);
    expect(await getAssistantDetailApi('assistant-28')).toBe(response);
  });
});
