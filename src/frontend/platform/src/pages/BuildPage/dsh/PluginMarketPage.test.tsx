import { useContext, type ReactNode } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { userContext } from '@/contexts/userContext';
import { PluginMarketPage } from './PluginMarketPage';
import * as market from '@/controllers/API/dshMarket';

vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: {} }) }));
vi.mock('@/controllers/API/dshMarket', () => ({ getMarketContext: vi.fn(), listMarketPlugins: vi.fn(), listMarketImports: vi.fn(), previewMarketBundle: vi.fn(), importMarketBundle: vi.fn(), getMarketPlugin: vi.fn(), deleteMarketPlugin: vi.fn(), resumeMarketImport: vi.fn() }));
interface FixtureProps { children: ReactNode; user?: Record<string, unknown> }
function Fixture({ children, user = { role: 'admin', user_id: 1, tenant_id: 2 } }: FixtureProps) {
  const defaults = useContext(userContext);
  return <userContext.Provider value={{ ...defaults, user }}>{children}</userContext.Provider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(market.getMarketContext).mockResolvedValue({ tenant_id: 2 });
  vi.mocked(market.listMarketPlugins).mockResolvedValue({ data: [], total: 0 });
  vi.mocked(market.listMarketImports).mockResolvedValue([]);
  vi.mocked(market.previewMarketBundle).mockResolvedValue({ name: 'plugin', display_name: 'Example plugin', current_version: null, incoming_version: '1.0.0', allowed: true, reason: 'new', duplicate: false });
  vi.mocked(market.importMarketBundle).mockResolvedValue({ id: 'job-1', status: 'completed', error: '', created_at: '' });
});
it('does not load market context for a user without administration rights', () => {
  render(<Fixture user={{ role: 'user' }}><PluginMarketPage /></Fixture>);
  expect(screen.getByText('forbidden')).toBeVisible();
  expect(market.getMarketContext).not.toHaveBeenCalled();
});
it('previews the chosen ZIP and imports it into the resolved tenant', async () => {
  const user = userEvent.setup(); render(<Fixture><PluginMarketPage /></Fixture>);
  await screen.findByText('empty'); await user.click(screen.getByRole('button', { name: 'import' }));
  const dialog = screen.getByRole('dialog');
  const input = within(dialog).getByLabelText('import');
  const file = new File(['fixture'], 'plugin.zip', { type: 'application/zip' });
  await user.upload(input, file);
  expect(await screen.findByText('Example plugin')).toBeVisible();
  await user.click(within(dialog).getByRole('button', { name: 'import' }));
  await waitFor(() => expect(market.importMarketBundle).toHaveBeenCalledWith(file, 2, expect.any(AbortSignal), expect.any(Function)));
});
it('blocks import when the preview reports a version conflict', async () => {
  vi.mocked(market.previewMarketBundle).mockResolvedValue({ name: 'plugin', display_name: 'Example plugin', current_version: '1.0.0', incoming_version: '1.0.0', allowed: false, reason: 'version_conflict', duplicate: true });
  const user = userEvent.setup(); render(<Fixture><PluginMarketPage /></Fixture>);
  await screen.findByText('empty'); await user.click(screen.getByRole('button', { name: 'import' }));
  const dialog = screen.getByRole('dialog');
  await user.upload(within(dialog).getByLabelText('import'), new File(['fixture'], 'plugin.zip', { type: 'application/zip' }));
  expect(await screen.findByText('versionConflict')).toBeVisible();
  expect(within(dialog).getByRole('button', { name: 'import' })).toBeDisabled();
  expect(market.importMarketBundle).not.toHaveBeenCalled();
});
