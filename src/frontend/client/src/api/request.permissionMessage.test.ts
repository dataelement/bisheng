import i18next from 'i18next';
import request from './request';
import translation from '~/locales/zh-Hans/translation.json';

const permissionDeniedMessage = 'Permission denied: only the creator or admin can perform this operation';

beforeAll(async () => {
  await i18next.init({
    lng: 'zh-Hans',
    resources: { 'zh-Hans': { translation } },
  });
});

test.each(['caller', 'showError', 'skip403Redirect'] as const)(
  '%s receives the Chinese permission message',
  async (mode) => {
    const toast = jest.fn();
    window.showToast = toast;
    const result = request.get('/api/v1/knowledge/space/3769/folders', {
      ...(mode === 'caller' ? {} : { [mode]: true }),
      adapter: async (config) => ({
        config,
        data: { status_code: 18040, status_message: permissionDeniedMessage, data: null },
        status: 200,
        statusText: 'OK',
        headers: {},
      }),
    });

    if (mode === 'skip403Redirect') {
      await expect(result).rejects.toThrow('无权限执行此操作');
    } else {
      await expect(result).resolves.toMatchObject({
        status_code: 18040,
        status_message: '无权限执行此操作',
      });
    }
    if (mode === 'caller') {
      expect(toast).not.toHaveBeenCalled();
    } else {
      expect(toast).toHaveBeenCalledTimes(1);
      expect(toast).toHaveBeenCalledWith({ message: '无权限执行此操作', status: 'error' });
    }
  },
);

test('preserves a specific Chinese permission reason', async () => {
  await expect(request.get('/api/v1/knowledge/space/3769/folders', {
    adapter: async (config) => ({
      config,
      data: { status_code: 18040, status_message: '当前账号没有分享该文档的权限', data: null },
      status: 200,
      statusText: 'OK',
      headers: {},
    }),
  })).resolves.toMatchObject({ status_message: '当前账号没有分享该文档的权限' });
});
