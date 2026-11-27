import request, { platformAuth } from '~/api/request';
import { getUser, logout } from './data-service';

jest.mock('~/api/request', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() }, platformAuth: { logout: jest.fn() } }));
const get = jest.mocked(request.get);

it.each(['000Case01', ` old account ${'x'.repeat(70)}`, null, undefined])('preserves the raw account independently of the display nickname: %j', async account => {
    get.mockResolvedValueOnce({ data: {
        user_id: 7, user_name: 'DisplayNickname', external_id: account, role: 'admin', web_menu: [],
        create_time: '', update_time: '',
    } });
    const user = await getUser();
    expect(user.username).toBe('DisplayNickname'); expect(user.name).toBe('DisplayNickname');
    expect(user.external_id).toBe(account ?? null);
    expect(user.external_id).not.toBe(user.username);
});

it('delegates logout to the shared controller without calling the legacy token endpoint', async () => {
    jest.mocked(platformAuth.logout).mockResolvedValueOnce(undefined);
    await expect(logout()).resolves.toEqual({ message: '' });
    expect(platformAuth.logout).toHaveBeenCalledTimes(1);
    expect(request.post).not.toHaveBeenCalled();
});
it('preserves failed remote revocation for the UI to report local-only logout', async () => {
    const failure = new Error('unconfirmed');
    jest.mocked(platformAuth.logout).mockRejectedValueOnce(failure);
    await expect(logout()).rejects.toBe(failure);
    expect(request.post).not.toHaveBeenCalled();
});
