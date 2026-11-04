import { act, renderHook } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import { addWechatSourceApi } from '~/api/channels';
import { useSourceManager } from './useSourceManager';
const mockConfirm = jest.fn();
const empty: never[] = [];
jest.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: empty }) }));
jest.mock('~/api/channels', () => ({
  SortType: { RECENT_UPDATE: 'latest_update' },
  getChannelsApi: jest.fn(),
  listManagerSourcesApi: jest.fn(async () => ({ sources: [], total: 0 })),
  searchManagerSourcesApi: jest.fn(async () => ({ sources: [], total: 0 })),
  addWechatSourceApi: jest.fn(),
}));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/useEffectiveQuota', () => ({ useEffectiveQuota: () => ({ quotas: {} }) }));
jest.mock('~/Providers', () => ({ useConfirm: () => mockConfirm }));
beforeEach(() => { jest.useFakeTimers(); mockConfirm.mockReset(); });
afterEach(() => jest.useRealTimers());
it.each(['business', 'canceled', 'global'] as const)('recovers a failed article link without confusing presentation with its status code: %s', async kind => {
  const error = normalizeApiError(kind === 'canceled' ? { code: 'ERR_CANCELED' } : { status_code: 19004 }, { message: 'unrecognized' });
  if (kind === 'global') error.presentation = 'global';
  (addWechatSourceApi as jest.Mock).mockRejectedValue(error);
  const { result } = renderHook(() => useSourceManager(empty, jest.fn(), true, jest.fn()));
  await act(async () => { result.current.submitSearch('https://mp.weixin.qq.com/s/test'); });
  await act(async () => { jest.advanceTimersByTime(1800); });
  expect(result.current.pendingSources).toEqual([]);
  expect(result.current.wechatLinkFailed).toBe(kind === 'business');
  expect(mockConfirm).toHaveBeenCalledTimes(kind === 'business' ? 1 : 0);
});

it('keeps failed initial source loads distinguishable from an empty successful list and retries', async () => {
  const { listManagerSourcesApi } = jest.requireMock('~/api/channels');
  const error = normalizeApiError({ status_code: 19004 }, { message: 'sources failed' });
  listManagerSourcesApi.mockRejectedValueOnce(error);
  const { result } = renderHook(() => useSourceManager(empty, jest.fn(), true, jest.fn()));
  await act(async () => {});
  expect(result.current.sourceListError).toBe(error);
  expect(result.current.viewMode).toBe('list');
  await act(async () => { result.current.retrySources(); });
  expect(result.current.sourceListError).toBeNull();
  expect(result.current.filteredSources).toEqual([]);
});
it.each(['list', 'search'])('preserves source rows when %s pagination fails and retries the same page', async mode => {
  const { listManagerSourcesApi, searchManagerSourcesApi } = jest.requireMock('~/api/channels');
  const error = normalizeApiError({ status_code: 19004 }, { message: 'more sources failed' });
  const page = { sources: [{ id: 'source', name: 'source', business_type: 'wechat' }], total: 40 };
  listManagerSourcesApi.mockResolvedValue(page);
  searchManagerSourcesApi.mockResolvedValue(page);
  const { result } = renderHook(() => useSourceManager(empty, jest.fn(), true, jest.fn()));
  await act(async () => {});
  if (mode === 'search') await act(async () => result.current.submitSearch('source'));
  const api = mode === 'list' ? listManagerSourcesApi : searchManagerSourcesApi;
  api.mockRejectedValueOnce(error);
  await act(async () => { await result.current.loadMoreSources(); });
  expect(result.current.sourceListError).toBe(error);
  expect(result.current.filteredSources.map(s => s.id)).toEqual(['source']);
  api.mockResolvedValueOnce({ sources: [{ id: 'second', name: 'source two', business_type: 'wechat' }], total: 40 });
  await act(async () => { await result.current.retrySources(); });
  expect(result.current.sourceListError).toBeNull();
  expect(result.current.filteredSources.map(s => s.id)).toEqual(['source', 'second']);
});
it('does not treat a failed source search as a successful missing website', async () => {
  const { searchManagerSourcesApi } = jest.requireMock('~/api/channels');
  const error = normalizeApiError({ status_code: 19004 }, { message: 'search failed' });
  searchManagerSourcesApi.mockRejectedValueOnce(error);
  const { result } = renderHook(() => useSourceManager(empty, jest.fn(), true, jest.fn()));
  await act(async () => {});
  await act(async () => result.current.submitSearch('https://example.com'));
  expect(result.current.sourceListError).toBe(error);
  expect(result.current.viewMode).toBe('list');
});
it('ignores a stale WeChat rejection after the user switches to a different search', async () => {
  const { listManagerSourcesApi, searchManagerSourcesApi } = jest.requireMock('~/api/channels');
  listManagerSourcesApi.mockResolvedValue({ sources: [], total: 0 });
  searchManagerSourcesApi.mockResolvedValue({ sources: [], total: 0 });
  let rejectRequest: (reason: unknown) => void = () => {};
  (addWechatSourceApi as jest.Mock).mockReturnValue(new Promise((_resolve, reject) => { rejectRequest = reject; }));
  const { result } = renderHook(() => useSourceManager(empty, jest.fn(), true, jest.fn()));
  await act(async () => {});
  await act(async () => result.current.submitSearch('https://mp.weixin.qq.com/s/old'));
  await act(async () => { jest.advanceTimersByTime(1800); });
  await act(async () => result.current.submitSearch('different search'));
  await act(async () => rejectRequest(normalizeApiError({ status_code: 19004 }, { message: 'old request failed' })));
  expect(result.current.wechatLinkFailed).toBe(false);
  expect(mockConfirm).not.toHaveBeenCalled();
});
