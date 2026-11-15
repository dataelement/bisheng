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
