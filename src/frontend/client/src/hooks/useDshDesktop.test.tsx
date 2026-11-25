import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useDshDesktop } from './useDshDesktop';
import { getDshBrowserConfig } from '~/api/dsh';
jest.mock('~/api/dsh', () => ({ getDshBrowserConfig: jest.fn() }));
it('disables the client entry when the business switch turns off', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  jest.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: null, launch_url: 'dsh-desktop://login' });
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result } = renderHook(useDshDesktop, { wrapper });
  await waitFor(() => expect(result.current.enabled).toBe(true));
  jest.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: false, download_url: null, launch_url: 'dsh-desktop://login' });
  await act(async () => { await client.refetchQueries(['dsh-browser-config']); });
  await waitFor(() => expect(result.current.enabled).toBe(false));
});

it('shares configuration across consumers and does not poll every 30 seconds', async () => {
  const client = new QueryClient();
  jest.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: null, launch_url: 'bisheng://login' });
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => [useDshDesktop(), useDshDesktop()], { wrapper });
  await waitFor(() => expect(view.result.current.every(value => value.enabled)).toBe(true));
  expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
  jest.useFakeTimers();
  try {
    await act(async () => { jest.advanceTimersByTime(90000); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
  } finally {
    view.unmount(); client.clear(); jest.useRealTimers();
  }
});

it('keeps desktop enabled while exposing creditBillingEnabled false when billing switch is off', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  jest.mocked(getDshBrowserConfig).mockResolvedValue({
    management_enabled: true,
    enabled: true,
    credit_billing_enabled: false,
    download_url: null,
    launch_url: 'dsh-desktop://login',
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result } = renderHook(useDshDesktop, { wrapper });
  await waitFor(() => expect(result.current.enabled).toBe(true));
  expect(result.current.creditBillingEnabled).toBe(false);
});
