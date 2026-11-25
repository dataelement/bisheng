import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useProviderFileUploads } from '~/pages/knowledge/hooks/useProviderFileUploads';
import { ProviderWikiEntry } from '~/pages/knowledge/SpaceDetail/ProviderWikiPage';

const http = vi.hoisted(() => ({ getResponse: vi.fn() }));
const identity = vi.hoisted(() => ({ id: '1', role: 'member', tenant_id: 7 }));
vi.mock('~/api/request', () => ({ default: http }));
vi.mock('~/hooks', () => ({ useLocalize: () => (k: string) => k, useAuthContext: () => ({ user: identity }) }));
const key = (s: string) => `com_knowledge.wiki.${s}`;
const nodes = ['summary', 'entity', 'concept'].map(t => ({ page_type: t, slug: `${t}/pump`, title: `${t} pump` }));
let state: string, generation: number | null, tenant: string, provider: string;
const envelope = (data: unknown) => ({ headers: { 'x-management-tenant': tenant }, data: { status_code: 200, data } });
const page = (slug: string) => ({ ...nodes.find(n => n.slug === slug), summary: 'Overview', content: '## Derived text\n[Label](https://remote.invalid) ![remote](https://remote.invalid/image)', in_links: [], out_links: ['concept/pump'], sources: [{ restricted: true, file_id: 77, url: 'secret' }, { file_id: 9 }] });
const read = (url: string, { params }: { params?: Record<string, string> }) => {
  if (url.endsWith('/capabilities')) return envelope({ provider_key: provider, capabilities: {}, capability_revision: 1 });
  if (url.endsWith('/status')) return envelope({ state, generation });
  if (url.endsWith('/graph')) return envelope({ nodes, edges: [{ source: nodes[0].slug, target: nodes[1].slug }] });
  if (url.endsWith('/search')) return envelope([{ ...nodes[1], summary: 'Found pump' }]);
  if (url.endsWith('/page') && params?.slug) return envelope(page(params.slug));
  throw new Error(`Unexpected request ${url}`);
};
beforeEach(() => { state = 'ready'; generation = 4; tenant = '7'; provider = 'weknora'; identity.id = '1'; identity.tenant_id = 7; http.getResponse.mockReset().mockImplementation(read); });
afterEach(cleanup);
function Entry({ id, allowed }: { id: string; allowed: boolean }) {
  const { wikiDiscovery } = useProviderFileUploads(id, undefined, false, () => {}, () => {});
  return <ProviderWikiEntry spaceId={id} canRead={allowed} discovery={wikiDiscovery} />;
}
function mount(canRead = true) {
  const client = new QueryClient();
  const tree = (id: string, allowed: boolean) => <MemoryRouter><QueryClientProvider client={client}><Entry id={id} allowed={allowed} /></QueryClientProvider></MemoryRouter>;
  const view = render(tree('11', canRead));
  return { update: (id = '11', allowed = true) => view.rerender(tree(id, allowed)), client };
}
const enter = async () => fireEvent.click(await screen.findByRole('button', { name: key('title') }));
it('opens actual generation-bound nodes and search hits, follows related pages and never loads provider URLs', async () => {
  mount(); await enter();
  const graph = await screen.findByRole('group', { name: key('graph') });
  expect(graph.querySelectorAll('line')).toHaveLength(1);
  fireEvent.click(within(graph).getByRole('button', { name: 'summary pump' }));
  await screen.findByRole('heading', { name: 'Derived text' });
  expect(screen.getByText(key('restricted'))).toBeTruthy();
  expect(document.querySelector('a[href*="remote"],img[src],a[href*="77"]')).toBeNull();
  expect(screen.getByRole('link').getAttribute('href')).toBe('/knowledge/file/9?spaceId=11');
  fireEvent.click(within(screen.getByRole('region', { name: key('related') })).getByRole('button', { name: 'concept pump' }));
  await screen.findByRole('heading', { name: 'concept pump' });
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: ' pump ' } });
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.search' }));
  fireEvent.click(await screen.findByRole('button', { name: /Found pump/ }));
  await screen.findByRole('heading', { name: 'entity pump' });
  const calls = http.getResponse.mock.calls.filter(([url]) => /\/(search|page|graph)$/.test(url));
  expect(calls.every(([url, options]) => url.startsWith('/api/v1/knowledge/space/11/wiki/') && options.params.generation === 4)).toBe(true);
  expect(calls.find(([url]) => url.endsWith('/search'))?.[1].params.q).toBe('pump');
});
it.each(['preparing', 'generating', 'updating', 'empty', 'query_failed'])('blocks graph/search/page in %s', async status => {
  state = status; if (status === 'preparing') generation = null;
  mount(); await enter(); await screen.findByText(key(status));
  expect(http.getResponse.mock.calls.filter(([url]) => /\/(search|page|graph)$/.test(url))).toEqual([]);
});
it.each(['native', 'other', 'denied'])('hides the entry and makes no Wiki read for %s', async scenario => {
  provider = scenario === 'denied' ? 'weknora' : scenario; mount(scenario !== 'denied');
  if (scenario !== 'denied') await waitFor(() => expect(http.getResponse).toHaveBeenCalled());
  expect(screen.queryByRole('button', { name: key('title') })).toBeNull();
  expect(http.getResponse.mock.calls.some(([url]) => url.includes('/wiki/'))).toBe(false);
});
it('discovers a preparing binding only through authorized status when capabilities return 18089', async () => {
  state = 'preparing'; generation = null;
  http.getResponse.mockImplementation((url, opts) => {
    if (url.endsWith('/capabilities')) throw Object.assign(new Error('Unavailable'), {
      status_code: 18089, response: { headers: { 'x-management-tenant': '7' } },
    });
    return read(url, opts);
  });
  mount(); await enter(); await screen.findByText(key('preparing'));
  expect(http.getResponse.mock.calls.some(([url]) => url.endsWith('/graph'))).toBe(false);
});
it.each(['malformed status', 'wrong tenant', 'denied status'])('never reveals an entry without valid proof: %s', async scenario => {
  http.getResponse.mockImplementation((url, opts) => {
    if (!url.endsWith('/status')) return read(url, opts);
    return scenario === 'wrong tenant' ? { ...envelope({ state: 'ready', generation: 4 }), headers: { 'x-management-tenant': '8' } }
      : scenario === 'denied status' ? { ...envelope({}), data: { status_code: 18089 } } : envelope({ state: 'ready', generation: null });
  });
  const { client } = mount();
  await waitFor(() => expect(client.getQueryCache().findAll(['wiki-status']).some(q => q.state.status === 'error')).toBe(true));
  expect(screen.queryByRole('button', { name: key('title') })).toBeNull();
});
it.each(['space', 'tenant', 'user', 'permission', 'generation'])('drops in-flight page and graph selection when %s changes', async change => {
  let complete!: (value: unknown) => void;
  http.getResponse.mockImplementation((url, opts) => url.endsWith('/page') ? new Promise(resolve => { complete = resolve; }) : read(url, opts));
  const { update, client } = mount(); await enter();
  fireEvent.click(await screen.findByRole('button', { name: 'entity pump' }));
  await waitFor(() => expect(complete).toBeDefined());
  if (change === 'generation') {
    generation = 5; await act(async () => { await client.refetchQueries(['wiki-status']); });
    await waitFor(() => expect(http.getResponse.mock.calls.some(([url, opts]) => url.endsWith('/graph') && opts.params.generation === 5)).toBe(true));
  } else {
    if (change === 'tenant') { tenant = '8'; identity.tenant_id = 8; }
    if (change === 'user') identity.id = '2';
    update(change === 'space' ? '12' : '11', change !== 'permission');
    expect(screen.queryByRole('dialog')).toBeNull();
    if (change !== 'permission') { await enter(); await screen.findByRole('group', { name: key('graph') }); }
  }
  await act(async () => { complete({ ...envelope({ ...page('entity/pump'), content: 'Obsolete secret' }), headers: { 'x-management-tenant': '7' } }); });
  expect(screen.queryByText('Obsolete secret')).toBeNull(); expect(screen.queryByRole('link')).toBeNull();
});
it('withdraws visible graph and detail when status becomes non-readable or access is revoked', async () => {
  const { client } = mount(); await enter(); fireEvent.click(await screen.findByRole('button', { name: 'entity pump' }));
  await screen.findByRole('heading', { name: 'Derived text' }); state = 'updating';
  await act(async () => { await client.refetchQueries(['wiki-status']); });
  await screen.findByText(key('updating')); expect(screen.queryByRole('group', { name: key('graph') })).toBeNull();
  expect(screen.queryByRole('heading', { name: 'Derived text' })).toBeNull();
  http.getResponse.mockRejectedValue(new Error('No access')); await act(async () => { await client.refetchQueries(['wiki-status']); });
  await screen.findByText(key('unavailable')); expect(screen.queryByRole('link')).toBeNull();
});
it.each(['bad page', 'wrong tenant', 'business error'])('rejects an unsafe detail response: %s', async scenario => {
  http.getResponse.mockImplementation((url, opts) => {
    if (!url.endsWith('/page')) return read(url, opts);
    const wrong = envelope({ ...page('entity/pump'), slug: scenario === 'bad page' ? 'concept/pump' : 'entity/pump' });
    return scenario === 'wrong tenant' ? { ...wrong, headers: { 'x-management-tenant': '8' } }
      : scenario === 'business error' ? { ...wrong, data: { ...wrong.data, status_code: 18089 } } : wrong;
  });
  mount(); await enter(); fireEvent.click(await screen.findByRole('button', { name: 'entity pump' }));
  await screen.findByText(key('query_failed')); expect(screen.queryByRole('heading', { name: 'Derived text' })).toBeNull();
});
