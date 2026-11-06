import { act, renderHook } from '@testing-library/react';
import type { PropsWithChildren, ComponentType } from 'react';
import { getFrequently, pinAppApi } from '~/api/apps';
import type { AppItem } from '~/@types/app';
import { useAppCenter } from './useAppCenter';

// Exercise the existing store with its real provider; the product state model stays unchanged.
const { RecoilRoot } = jest.requireActual<{ RecoilRoot: ComponentType<PropsWithChildren> }>('recoil');
const mockShowToast = jest.fn();
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn(), useLocation: () => ({ pathname: '/apps' }) }));
jest.mock('~/api/apps', () => ({ getFrequently: jest.fn(), pinAppApi: jest.fn() }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockShowToast }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/pages/apps/appUtils', () => ({ getAppShareUrl: jest.fn() }));
jest.mock('~/utils', () => ({ copyText: jest.fn(), generateUUID: jest.fn() }));
jest.mock('~/common', () => ({ NotificationSeverity: { INFO: 'info', WARNING: 'warning', SUCCESS: 'success' } }));

const app: AppItem = { id: 'asst-1', name: 'Assistant', description: '', logo: '', user_id: '7', flow_type: 5, is_pinned: false };
const mockList = jest.mocked(getFrequently);
const mockPin = jest.mocked(pinAppApi);

beforeEach(() => {
  mockPin.mockReset();
  mockList.mockReset();
  mockList.mockResolvedValue({ status_code: 200, data: { list: [app], total: 1 } });
});

it('reads persisted pin state after pin, reload and unpin', async () => {
  let pinned = false;
  mockPin.mockImplementation(async (_id, value) => { pinned = value; return { status_code: 200 }; });
  mockList.mockImplementation(async () => ({ status_code: 200, data: { list: [{ ...app, is_pinned: pinned }], total: 1 } }));
  const view = renderHook(() => useAppCenter(), { wrapper: RecoilRoot });
  await act(async () => { await view.result.current.fetchApps(); });
  await act(async () => { await view.result.current.togglePin(view.result.current.apps[0]); });
  expect(view.result.current.apps[0].is_pinned).toBe(true);
  view.unmount();
  const reloaded = renderHook(() => useAppCenter(), { wrapper: RecoilRoot });
  await act(async () => { await reloaded.result.current.fetchApps(); });
  expect(reloaded.result.current.apps[0].is_pinned).toBe(true);
  await act(async () => { await reloaded.result.current.togglePin(reloaded.result.current.apps[0]); });
  expect(reloaded.result.current.apps[0].is_pinned).toBe(false);
  expect(mockPin.mock.calls).toEqual([['asst-1', true], ['asst-1', false]]);
  expect(mockShowToast).toHaveBeenCalledTimes(0);
});

it.each([false, true])('reports business failure and preserves pinned=%s', async (pinned) => {
  const current = { ...app, is_pinned: pinned };
  mockList.mockResolvedValue({ status_code: 200, data: { list: [current], total: 1 } });
  mockPin.mockResolvedValue({ status_code: 12015, status_message: 'App unavailable' });
  const { result } = renderHook(() => useAppCenter(), { wrapper: RecoilRoot });
  await act(async () => { await result.current.fetchApps(); });
  await act(async () => { await result.current.togglePin(result.current.apps[0]); });
  expect(result.current.apps[0].is_pinned).toBe(pinned);
  expect(mockList).toHaveBeenCalledTimes(1);
  expect(mockShowToast).toHaveBeenCalledWith({ message: pinned ? 'com_app_unpin_failed' : 'com_app_pin_failed', severity: 'warning' });
});

it('reports a network failure and keeps the current list', async () => {
  mockPin.mockRejectedValue(new Error('Network error'));
  const { result } = renderHook(() => useAppCenter(), { wrapper: RecoilRoot });
  await act(async () => { await result.current.fetchApps(); });
  await act(async () => { await result.current.togglePin(result.current.apps[0]); });
  expect(result.current.apps).toEqual([app]);
  expect(mockList).toHaveBeenCalledTimes(1);
  expect(mockShowToast).toHaveBeenCalledWith({ message: 'com_app_pin_failed', severity: 'warning' });
});
