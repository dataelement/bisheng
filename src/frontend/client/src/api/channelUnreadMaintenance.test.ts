import request from './request';
import { getChannelUnreadCountsApi } from './channels';

let mockStatus = 200;
let mockData: Record<string, unknown> = {};

// Keep the real Axios interceptor pipeline; replace only the network adapter.
jest.mock('axios', () => {
    const actual = jest.requireActual<typeof import('axios')>('axios');
    return {
        ...actual,
        __esModule: true,
        default: {
            ...actual.default,
            create: (options: Parameters<typeof actual.default.create>[0]) => actual.default.create({
                ...options,
                adapter: async (config) => {
                    const response = { config, data: mockData, status: mockStatus, statusText: '', headers: {} };
                    if (mockStatus >= 400) {
                        throw new actual.AxiosError('Service unavailable', 'ERR_BAD_RESPONSE', config, undefined, response);
                    }
                    return response;
                },
            }),
        },
    };
});

jest.mock('~/api/chat/headers-helpers', () => ({ setTokenHeader: jest.fn() }));
jest.mock('~/utils/loginRedirect', () => ({ redirectToLogin: jest.fn() }));

describe('channel unread-count failure isolation', () => {
    const onMaintenance = jest.fn();

    beforeEach(() => {
        mockStatus = 200;
        mockData = { status_code: 500, status_message: 'ES timed out', data: null };
        window.addEventListener('bs:service-maintenance', onMaintenance);
    });

    afterEach(() => {
        window.removeEventListener('bs:service-maintenance', onMaintenance);
    });

    it.each([200, 500])('keeps unread-count failure local for HTTP %s', async (status) => {
        mockStatus = status;

        await expect(getChannelUnreadCountsApi('channel-1')).rejects.toThrow();

        expect(onMaintenance).not.toHaveBeenCalled();
    });

    it.each([200, 500])('preserves the global overlay for other requests with HTTP %s', async (status) => {
        mockStatus = status;

        await request.get('/api/v1/channel/manager/channel-1').catch(() => undefined);

        expect(onMaintenance).toHaveBeenCalledTimes(1);
    });

    it('returns successful unread counts unchanged', async () => {
        mockData = { status_code: 200, data: { news: 3 } };

        await expect(getChannelUnreadCountsApi('channel-1')).resolves.toEqual({ news: 3 });

        expect(onMaintenance).not.toHaveBeenCalled();
    });
});
