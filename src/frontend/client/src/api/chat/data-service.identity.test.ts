import request from '~/api/request';
import { getUser } from './data-service';

jest.mock('~/api/request', () => ({ __esModule: true, default: { get: jest.fn() } }));
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
