import request from './request';
import { updateNicknameApi } from './user';

jest.mock('./request', () => ({ __esModule: true, default: { patch: jest.fn() } }));
const patch = jest.mocked(request.patch);
beforeEach(() => jest.clearAllMocks());

it('sends the raw nickname without a target user id and returns only the validated profile', async () => {
    const profile = { user_id: 7, user_name: 'Nickname𠮷', external_id: '000Case01' };
    patch.mockResolvedValueOnce({ status_code: 200, data: profile });
    await expect(updateNicknameApi(profile.user_name)).resolves.toEqual(profile);
    expect(patch).toHaveBeenCalledWith('/api/v1/user/profile/nickname', { user_name: profile.user_name });
});

it.each([
    null, {}, { status_code: 10614, data: null },
    { status_code: 200, data: { user_name: 'Incomplete' } },
    { status_code: 200, data: { user_id: 7, user_name: 'Nickname', external_id: 1 } },
    { status_code: 200, data: { user_id: 0, user_name: 'Nickname', external_id: 'Account' } },
])('rejects an invalid response instead of reporting a successful nickname change: %j', async response => {
    patch.mockResolvedValueOnce(response);
    await expect(updateNicknameApi('Nickname')).rejects.toThrow('Invalid nickname update response');
});

it('keeps a network failure rejected for the editor to retain its draft', async () => {
    const error = new Error('network unavailable'); patch.mockRejectedValueOnce(error);
    await expect(updateNicknameApi('Nickname')).rejects.toBe(error);
});
