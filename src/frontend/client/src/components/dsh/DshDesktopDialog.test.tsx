import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DshDesktopDialog } from './DshDesktopDialog';
import { getDshSessions, getDshUsage, revokeDshSession } from '~/api/dsh';

jest.mock('~/api/dsh', () => ({ getDshSessions: jest.fn(), getDshUsage: jest.fn(), revokeDshSession: jest.fn(), dshLaunchUrl: () => 'dsh-desktop://login' }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: { id: '20' } }) }));
jest.mock('~/Providers/ConfirmContext', () => ({ useConfirm: () => async () => true }));
jest.mock('@bisheng/ui', () => ({ Button: ({ children, onClick, disabled }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean }) => <button onClick={onClick} disabled={disabled}>{children}</button> }));
jest.mock('~/components/ui/Dialog', () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div role="dialog">{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}));
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } }, logger: { log: () => undefined, warn: console.warn, error: () => undefined } });
  return render(<QueryClientProvider client={client}><DshDesktopDialog open onOpenChange={jest.fn()} downloadUrl={null} /></QueryClientProvider>);
}
beforeEach(() => {
  jest.mocked(getDshSessions).mockResolvedValue({ items: [], next_cursor: null, has_more: false });
  jest.mocked(getDshUsage).mockResolvedValue({ month: '2026-09', billing_timezone: 'Asia/Shanghai', source: 'unavailable', as_of: null, unknown_pending: null, models: [] });
});
it('shows a never-logged-in user with no sessions or models and no download link', async () => {
  show();
  await screen.findByText('dsh_no_sessions');
  expect(screen.getByText('dsh_no_models')).toBeInTheDocument();
  expect(screen.queryByText('dsh_download')).not.toBeInTheDocument();
  expect(revokeDshSession).not.toHaveBeenCalled();
});
it('revokes exactly the selected device and refreshes its status', async () => {
  const rows = ['first', 'second'].map((id) => ({ session_id: id, device_label: id, client_version: null, state: 'ACTIVE', created_at: '2026-09-10T00:00:00Z', last_seen_at: null, expires_at: '2026-10-10T00:00:00Z' }));
  jest.mocked(getDshSessions).mockResolvedValue({ items: rows, next_cursor: null, has_more: false });
  jest.mocked(revokeDshSession).mockImplementation(async () => {
    jest.mocked(getDshSessions).mockResolvedValue({ items: [{ ...rows[0], state: 'REVOKED' }, rows[1]], next_cursor: null, has_more: false });
  });
  show();
  await screen.findByText('first');
  fireEvent.click(screen.getAllByText('dsh_revoke')[0]);
  await waitFor(() => expect(revokeDshSession).toHaveBeenCalledWith('first'));
  await screen.findByText('dsh_state_REVOKED');
  expect(screen.getAllByText('dsh_revoke')).toHaveLength(1);
});
it('marks unavailable usage and keeps the model quota separate from unknown usage', async () => {
  jest.mocked(getDshUsage).mockResolvedValue({ month: '2026-09', billing_timezone: 'Asia/Shanghai', source: 'unavailable', as_of: null, unknown_pending: 1, models: [{ model_id: 4, name: 'Provider / model', limit: 100, used: null, remaining: null }] });
  show(); await screen.findByText('Provider / model');
  expect(screen.getByText('dsh_unknown_usage')).toBeInTheDocument();
  expect(screen.getByText(/dsh_source_unavailable/)).toBeInTheDocument();
  expect(screen.getByText('100')).toBeInTheDocument();
});
