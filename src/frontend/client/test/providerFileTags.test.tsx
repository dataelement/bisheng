import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';

const http = vi.hoisted(() => ({ getResponse: vi.fn() }));
vi.mock('~/api/request', () => ({
  default: http,
  prepareBrowserHeaders: async () => ({ 'X-Management-Tenant': '7' }),
  showApiError: vi.fn(),
}));
vi.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));

const scope = { kind: 'provider' as const, key: '9/7/1', generation: 1, tenant: '7', editable: true };
const body = (names: string[]) => ({ status_code: 200, data: { generation: 1, names } });
const reply = (names: string[]) => ({ headers: { 'x-management-tenant': '7' }, data: body(names) });

function Wrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}

// jsdom has no ResizeObserver; TagGroup measures overflow with it.
vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function mount() {
  const { ProviderFileTags } = await import('~/pages/knowledge/SpaceDetail/ProviderFileTags');
  render(<ProviderFileTags spaceId="9" fileId="40" scope={scope} />, { wrapper: Wrapper });
}

it('does not read any document tags until the user asks for them', async () => {
  await mount();
  await screen.findByRole('button', { name: 'com_knowledge.provider_tags.show_names' });
  // A page of rows must not cost one slow remote call per row.
  expect(http.getResponse).not.toHaveBeenCalled();
});

it('shows the document names after one read, and requests the labels route once', async () => {
  http.getResponse.mockResolvedValue(reply(['Alpha', 'Beta', 'Gamma']));
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.provider_tags.show_names' }));
  // TagGroup renders a hidden measurement copy of every tag, so match all.
  await screen.findAllByText('#Alpha');
  await screen.findAllByText('#Gamma');
  expect(http.getResponse).toHaveBeenCalledTimes(1);
  expect(http.getResponse.mock.calls[0][0]).toBe('/api/v1/knowledge/space/9/files/40/provider-tag-labels');
});

it('reports an untagged document and a failed read distinctly', async () => {
  http.getResponse.mockResolvedValueOnce(reply([]));
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.provider_tags.show_names' }));
  await screen.findByText('com_knowledge.provider_tags.none');
  cleanup();
  http.getResponse.mockRejectedValueOnce({ status_code: 18089 });
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.provider_tags.show_names' }));
  await screen.findByText('com_knowledge.provider_tags.names_unavailable');
});
