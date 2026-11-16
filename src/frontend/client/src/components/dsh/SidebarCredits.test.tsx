import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { SidebarCredits } from './SidebarCredits';
import { getDshCredits } from '~/api/dsh';
import type { DshCredits } from '~/api/dsh';
import { renderHook } from '@testing-library/react';
import { resetDesktopConversationBridge, useDesktopConversationActivity } from '~/components/Chat/desktopConversationBridge';

jest.mock('~/api/dsh', () => ({ getDshCredits: jest.fn() }));
jest.mock('~/hooks', () => ({ useAuthContext: () => ({ user: { id: '20' } }) }));
const dsh = { enabled: true };
jest.mock('~/hooks/useDshDesktop', () => ({ useDshDesktop: () => dsh }));
jest.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));

const credits: DshCredits = { limit: '1000', used: '100.51272', remaining: '899.48728', reset_at: '2026-11-30T16:00:00Z', billing_timezone: 'Asia/Shanghai', unlimited: false };

function Where() {
  return <p data-testid="path">{useLocation().pathname}</p>;
}
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } }, logger: { log: () => undefined, warn: () => undefined, error: () => undefined } });
  const navigate = jest.fn();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/c/new']}>
        <SidebarCredits onNavigate={navigate} />
        <Routes><Route path="*" element={<Where />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return navigate;
}

beforeEach(() => {
  dsh.enabled = true;
  resetDesktopConversationBridge();
  jest.mocked(getDshCredits).mockReset().mockResolvedValue(credits);
});

it('F016: shows the remaining balance with two decimals and opens the credits card', async () => {
  const navigate = show();
  const row = await screen.findByRole('button', { name: /dsh.creditsRemaining/ });
  expect(row).toHaveTextContent('899.49 / 1,000');
  fireEvent.click(row);
  expect(screen.getByTestId('path')).toHaveTextContent('/settings/desktop');
  expect(navigate).toHaveBeenCalled();
});

it('F016: an exhausted member sees the raised allowance with what is left of it', async () => {
  jest.mocked(getDshCredits).mockResolvedValue({ ...credits, limit: '1000', used: '500', remaining: '500' });
  show();
  expect(await screen.findByRole('button', { name: /dsh.creditsRemaining/ })).toHaveTextContent('500 / 1,000');
});

it('F016: says unlimited instead of a number', async () => {
  jest.mocked(getDshCredits).mockResolvedValue({ ...credits, unlimited: true, remaining: null });
  show();
  expect(await screen.findByRole('button', { name: /dsh.creditsRemaining/ })).toHaveTextContent('dsh.creditsUnlimited');
});

it('F016: stays out of the sidebar when the balance is unreadable or the deployment has no desktop management', async () => {
  jest.mocked(getDshCredits).mockRejectedValue(new Error('26126'));
  show();
  await waitFor(() => expect(getDshCredits).toHaveBeenCalled());
  expect(screen.queryByRole('button')).toBeNull();
  dsh.enabled = false;
  jest.mocked(getDshCredits).mockClear();
  show();
  expect(getDshCredits).not.toHaveBeenCalled();
});

it('F016: rereads the balance shortly after a chat turn finishes', async () => {
  jest.useFakeTimers();
  try {
    show();
    await act(async () => { await Promise.resolve(); });
    await waitFor(() => expect(getDshCredits).toHaveBeenCalledTimes(1));
    jest.mocked(getDshCredits).mockResolvedValue({ ...credits, remaining: '898.1' });
    const turn = renderHook(({ ids }) => useDesktopConversationActivity('chat-1', ids), { initialProps: { ids: ['c1'] } });
    turn.rerender({ ids: [] });
    await act(async () => { jest.advanceTimersByTime(1500); });
    await waitFor(() => expect(screen.getByRole('button', { name: /dsh.creditsRemaining/ })).toHaveTextContent('898.1'));
    // A new conversation's title call is charged a few seconds later; the second read picks it up.
    jest.mocked(getDshCredits).mockResolvedValue({ ...credits, remaining: '897.3' });
    await act(async () => { jest.advanceTimersByTime(18500); });
    await waitFor(() => expect(screen.getByRole('button', { name: /dsh.creditsRemaining/ })).toHaveTextContent('897.3'));
  } finally {
    jest.useRealTimers();
  }
});
