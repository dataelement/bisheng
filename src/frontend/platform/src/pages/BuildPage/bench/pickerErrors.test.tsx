import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import OrgKbConfig from './OrgKbConfig';
import ToolsConfig from './ToolsConfig';

const mock = vi.hoisted(() => ({ kb: vi.fn(), tools: vi.fn(), report: vi.fn(), notice: vi.fn() }));
vi.mock('@/controllers/API/knowledgeSpace', () => ({ listVisibleSpaces: mock.kb }));
vi.mock('@/hooks/useKnowledgePageScope', () => ({ useKnowledgePageScope: () => ({ scopes: { ordinary: { identityKey: 'user:7', tenantId: 101, managementTenantId: 101 } } }) }));
const clients: QueryClient[] = [];
function wrapper({ children }: { children: ReactNode }) { return <QueryClientProvider client={clients[clients.length - 1]}>{children}</QueryClientProvider>; }
vi.mock('@/controllers/API/tools', () => ({ getToolsApi: mock.tools }));
vi.mock('@/controllers/request', () => ({ showApiError: mock.report }));
vi.mock('@bisheng/ui', async (original) => ({ ...await original<typeof import('@bisheng/ui')>(), notification: { open: mock.notice } }));
beforeEach(() => { vi.clearAllMocks(); clients.push(new QueryClient({ defaultOptions: { queries: { retry: false } } })); });
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });

it.each(['knowledge', 'tools'])('offers retry instead of an empty %s picker after failure', async (kind) => {
    const error = new Error('Unavailable');
    const read = kind === 'knowledge' ? mock.kb : mock.tools;
    read.mockRejectedValueOnce(error).mockResolvedValueOnce(kind === 'knowledge' ? { data: [] } : []);
    render(kind === 'knowledge' ? <OrgKbConfig orgKbs={[]} onChange={vi.fn()} /> : <ToolsConfig tools={[]} onChange={vi.fn()} />, { wrapper });
    const retry = await screen.findByRole('button', { name: 'build.retry' });
    expect(mock.report).toHaveBeenCalledWith(error);
    expect(mock.notice).not.toHaveBeenCalled();
    expect(screen.queryByText(kind === 'knowledge' ? 'bench.noMatchKbs' : 'toolSelector.noToolsFound')).not.toBeInTheDocument();
    fireEvent.click(retry);
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'build.retry' })).not.toBeInTheDocument());
});

it('retains existing knowledge rows when a later search fails', async () => {
    mock.kb.mockResolvedValueOnce({ data: [{ id: 1, name: 'Knowledge A' }] }).mockRejectedValueOnce(new Error('Search failed'));
    render(<OrgKbConfig orgKbs={[]} onChange={vi.fn()} />, { wrapper });
    await screen.findByText('Knowledge A');
    fireEvent.change(screen.getByPlaceholderText('bench.searchKbName'), { target: { value: 'Knowledge' } });
    await screen.findByRole('button', { name: 'build.retry' });
    expect(screen.getByText('Knowledge A')).toBeVisible();
    expect(mock.notice).not.toHaveBeenCalled();
});
