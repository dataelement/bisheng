import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DshDesktopDialog } from './DshDesktopDialog';
import { getDshUsageSummary } from '~/api/dsh';
import type { DshUsageTimeSummary } from '~/api/dsh';

jest.mock('~/api/dsh', () => ({ getDshUsageSummary: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: { id: '20' } }) }));
jest.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, values?: Record<string, unknown>) => values ? `${key} ${JSON.stringify(values)}` : key, i18n: { language: 'en' } }) }));
jest.mock('@bisheng/ui', () => ({ Button: ({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) => <button onClick={onClick}>{children}</button> }));
jest.mock('~/components/ui/Dialog', () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div role="dialog">{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}));
const metrics = { message_count: 2, qa_count: 2, failed_count: 0, cancelled_count: 0, running_count: 0, usage_unknown_count: 0, recorded_usage_count: 2, missing_usage_count: 0, input_tokens: 60, output_tokens: 40, total_tokens: 100 };
const summary: DshUsageTimeSummary = { start_at: '2025-09-18T00:00:00+08:00', end_at: '2026-09-17T12:00:00+08:00', timezone: 'Asia/Shanghai', granularity: 'day', totals: metrics, points: [{ ...metrics, start_at: '2026-09-17T00:00:00+08:00', end_at: '2026-09-17T12:00:00+08:00' }] };
function show(downloadUrl: string | null = null, open = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } }, logger: { log: () => undefined, warn: console.warn, error: () => undefined } });
  return render(<QueryClientProvider client={client}><DshDesktopDialog open={open} onOpenChange={jest.fn()} downloadUrl={downloadUrl} launchUrl="dsh-desktop://login" /></QueryClientProvider>);
}
beforeEach(() => { jest.mocked(getDshUsageSummary).mockResolvedValue(summary); });
it('renders the annual calendar and synchronizes metric totals and tooltip', async () => {
  show();
  const calendar = await screen.findByRole('list', { name: 'dsh.tokenActivity' });
  expect(within(calendar).getAllByRole('button')).toHaveLength(365);
  expect(calendar).toHaveAttribute('data-rows', '7');
  const today = within(calendar).getAllByRole('button').at(-1)!;
  expect(today).toHaveStyle({ width: '12px', height: '12px' });
  fireEvent.pointerEnter(today);
  expect(screen.getByRole('tooltip')).toHaveTextContent('100');
  fireEvent.pointerLeave(calendar);
  fireEvent.click(screen.getByRole('button', { name: 'dsh.messageCount' }));
  expect(screen.getByRole('list', { name: 'dsh.messageActivity' })).toHaveAttribute('data-heatmap-metric', 'messages');
  expect(document.querySelector('[data-usage-totals]')).toHaveTextContent('2');
  for (const key of ['dsh_intro', 'dsh_download_help', 'dsh_sessions', 'dsh_quota_help', 'dsh_month_usage']) expect(screen.queryByText(key)).toBeNull();
});
it('uses the configured download link', async () => {
  const launch = jest.spyOn(window, 'open').mockImplementation(() => null);
  show('https://downloads.example.org/dsh.dmg');
  await screen.findByRole('list');
  fireEvent.click(screen.getByRole('button', { name: 'dsh_download' }));
  expect(launch).toHaveBeenCalledWith('https://downloads.example.org/dsh.dmg', '_blank', 'noopener,noreferrer');
});
it.each([
  ['https://downloads.example.org/dsh.dmg', 'dsh.launchHelp'],
  [null, 'dsh.launchHelpNoDownload'],
])('offers launch guidance with download URL %s without opening a download automatically', async (downloadUrl, helpKey) => {
  const originalLocation = window.location;
  const assign = jest.fn();
  const openWindow = jest.spyOn(window, 'open').mockImplementation(() => null);
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { origin: 'http://localhost:3080', assign },
  });
  try {
    show(downloadUrl);
    await screen.findByRole('list');
    expect(screen.queryByText(helpKey!)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'dsh_open' }));
    expect(assign).toHaveBeenCalledWith('dsh-desktop://login?server=http%3A%2F%2Flocalhost%3A3080');
    expect(screen.getByRole('status')).toHaveTextContent(helpKey!);
    expect(openWindow).not.toHaveBeenCalled();
  } finally {
    Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
  }
});
it('keeps usage unavailable distinct from zero', async () => {
  const unknown = { ...metrics, total_tokens: null, input_tokens: null, output_tokens: null, recorded_usage_count: 0, missing_usage_count: 2 };
  jest.mocked(getDshUsageSummary).mockResolvedValue({ ...summary, totals: unknown, points: [{ ...summary.points[0], ...unknown }] });
  show();
  await screen.findByText('dsh.unavailable');
  expect(screen.getByRole('status')).toHaveTextContent('dsh.missingUsageCount');
  expect(document.querySelector('[data-usage-unknown="true"]')).toBeInTheDocument();
  expect(screen.queryByText('dsh_download')).toBeNull();
});
it('allows retry after a summary request fails', async () => {
  jest.mocked(getDshUsageSummary).mockRejectedValueOnce(new Error('offline'));
  show();
  await screen.findByRole('alert');
  fireEvent.click(screen.getByText('dsh_retry'));
  await screen.findByRole('list');
  await waitFor(() => expect(getDshUsageSummary).toHaveBeenCalledTimes(2));
});
it('fetches on opening the dialog', () => {
  show(null, false);
  expect(getDshUsageSummary).not.toHaveBeenCalled();
});
