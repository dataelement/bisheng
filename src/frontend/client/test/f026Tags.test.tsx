import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';
import { CompoundSearchInput } from '~/pages/knowledge/SpaceDetail/CompoundSearchInput';
import { EditTagsModal } from '~/pages/knowledge/SpaceDetail/EditTagsModal';
import { useSpaceCapabilities } from '~/pages/knowledge/hooks/useSpaceCapabilities';

const native = vi.hoisted(() => ({ getSpaceTagsApi: vi.fn(), updateFileTagsApi: vi.fn() }));
const http = vi.hoisted(() => ({ getResponse: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock('~/api/knowledge', () => native);
vi.mock('~/api/request', () => ({ default: http, prepareBrowserHeaders: async () => ({ 'X-Management-Tenant': '7' }), showApiError: vi.fn() }));
vi.mock('~/hooks', () => ({ useLocalize: () => (k: string) => k, useAuthContext: () => ({ user: { id: '17', tenant_id: 7, role: 'member' } }) }));
vi.mock('~/hooks/useSelectCopy', () => ({ default: () => ({}) }));
vi.mock('~/utils', () => ({ cn: (...s: string[]) => s.join(' '), getFullWidthLength: (s: string) => s.length }));
vi.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: vi.fn() }) }));
vi.mock('~/pages/knowledge/hooks/useKnowledgeBatch', () => ({ useKnowledgeBatch: () => ({ view: null }) }));
vi.mock('~/pages/knowledge/SpaceDetail/BatchOperationDialog', () => ({ BatchOperationDialog: () => null }));
vi.mock('~/components/ui', async () => ({ ...await import('~/components/ui/Dialog'), ...await import('~/components/ui/Button'), ...await import('~/components/ui/Input') }));

const nativeScope = { kind: 'native' as const, key: 'member-7' };
const unavailable = { kind: 'unavailable' as const };
const words = Array.from({ length: 550 }, (_, i) => ({ id: i + 1, name: `Word ${i + 1}` }));
const key = (s: string) => `com_knowledge.provider_tags.${s}`;
function Wrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => { vi.clearAllMocks(); native.getSpaceTagsApi.mockResolvedValue(words); });
afterEach(cleanup);
const providerScope = { kind: 'provider' as const, key: '11/7/4', generation: 4, tenant: '7', editable: true };
const snapshot = (refs: number[], revision = 9) => ({ generation: 4, revision, edit_contract: 'manual-tags-v1', tag_ref_ids: refs });
const envelope = (data: unknown) => ({ headers: { 'x-management-tenant': '7' }, data: { status_code: 200, data } });
const readTags = (url: string, { params }: { params: { generation: number; page: number; page_size: number } }) => {
  expect(params.generation).toBe(4);
  if (url === '/api/v1/knowledge/space/11/files/3/provider-tags') return envelope(snapshot([701]));
  expect(url).toBe('/api/v1/knowledge/space/11/provider-tags');
  const start = (params.page - 1) * params.page_size;
  return envelope({ generation: 4, total: 550, data: words.slice(start, start + params.page_size).map(w => ({ tag_ref_id: w.id, name: w.name, usage: 'DO NOT SHOW' })) });
};
const openProvider = (onSaved = vi.fn(), editable = true) => render(<EditTagsModal isOpen canEditFileTags canReadSpaceTags spaceId="11" fileId="3"
  tagScope={{ ...providerScope, editable }} initialTagIds={[12345]} onClose={vi.fn()} onSaved={onSaved} />, { wrapper: Wrapper });
it('uses the provider catalog one page at a time, retaining previously unseen manual refs and new picks on save', async () => {
  http.getResponse.mockImplementation(readTags); http.put.mockResolvedValue({ status_code: 200, data: snapshot([701, 550], 10) });
  const saved = vi.fn(); openProvider(saved);
  await screen.findByRole('button', { name: 'Word 1' });
  expect(screen.queryByText('DO NOT SHOW')).toBeNull();
  for (let i = 2; i <= 11; i++) {
    fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.move_next_page' }));
    await screen.findByRole('button', { name: `Word ${(i - 1) * 50 + 1}` });
  }
  fireEvent.click(screen.getByRole('button', { name: 'Word 550' }));
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.move_previous_page' }));
  await screen.findByRole('button', { name: 'Word 451' });
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await vi.waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(http.put.mock.calls[0].slice(0,2)).toEqual(['/api/v1/knowledge/space/11/files/3/provider-tags', { generation: 4, mode: 'replace', expected_revision: 9, tag_ref_ids: [701,550] }]);
  expect(native.getSpaceTagsApi).not.toHaveBeenCalled(); expect(native.updateFileTagsApi).not.toHaveBeenCalled();
});
it('creates one space word on demand and attaches it with the frozen revision', async () => {
  http.getResponse.mockImplementation(readTags);
  http.post.mockResolvedValue({ status_code: 200, data: { tag_ref_id: 812, name: 'Pressure test', generation: 4 } });
  http.put.mockResolvedValue({ status_code: 200, data: snapshot([701, 812], 10) });
  const saved = vi.fn();
  render(<EditTagsModal isOpen canEditFileTags canReadSpaceTags canManageSpaceTags spaceId="11" fileId="3"
    tagScope={providerScope} onClose={vi.fn()} onSaved={saved} />, { wrapper: Wrapper });
  const input = await screen.findByPlaceholderText(key('new_word_placeholder'));
  fireEvent.change(input, { target: { value: '  Pressure test  ' } });
  fireEvent.click(screen.getByRole('button', { name: key('new_word') }));
  await vi.waitFor(() => expect(http.post).toHaveBeenCalledOnce());
  expect(http.post.mock.calls[0].slice(0, 2)).toEqual(['/api/v1/knowledge/space/11/provider-tags',
    { generation: 4, name: 'Pressure test' }]);
  const chip = await screen.findByRole('button', { name: 'Pressure test' });
  expect(chip.getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await vi.waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(http.put.mock.calls[0].slice(0, 2)).toEqual(['/api/v1/knowledge/space/11/files/3/provider-tags',
    { generation: 4, mode: 'replace', expected_revision: 9, tag_ref_ids: [701, 812] }]);
});
it('opens single-file provider editing even when the space permission summary has not resolved', async () => {
  http.getResponse.mockImplementation(readTags);
  render(<EditTagsModal isOpen canEditFileTags canManageSpaceTags spaceId="11" fileId="3"
    tagScope={providerScope} onClose={vi.fn()} />, { wrapper: Wrapper });
  await screen.findByPlaceholderText(key('new_word_placeholder'));
  expect(screen.queryByText(key('edit_unavailable'))).toBeNull();
});
it('reports batch tagging as unavailable for an external space without calling either API', async () => {
  render(<EditTagsModal isOpen canReadSpaceTags canManageSpaceTags spaceId="11" fileIds={['3', '4']}
    tagScope={providerScope} onClose={vi.fn()} />, { wrapper: Wrapper });
  await screen.findByText(key('batch_unavailable'));
  expect(screen.queryByText(key('edit_unavailable'))).toBeNull();
  expect(http.getResponse).not.toHaveBeenCalled(); expect(http.put).not.toHaveBeenCalled();
});
it('warns and saves through the whole-set contract when the upstream has no manual route', async () => {
  const whole = (refs: number[]) => ({ ...snapshot(refs), edit_contract: 'whole-tags-v1' });
  http.getResponse.mockImplementation((url: string, opts: never) =>
    url.includes('/files/') ? envelope(whole([701])) : readTags(url, opts));
  http.put.mockResolvedValue({ status_code: 200, data: whole([701, 2]) });
  const saved = vi.fn();
  openProvider(saved);
  await screen.findByText(key('whole_set_warning'));
  fireEvent.click(await screen.findByRole('button', { name: 'Word 2' }));
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await vi.waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(http.put.mock.calls[0].slice(0, 2)).toEqual(['/api/v1/knowledge/space/11/files/3/provider-tags',
    { generation: 4, mode: 'replace', expected_revision: 9, tag_ref_ids: [701, 2] }]);
});
it('never offers a new word without space tag management and never writes after a failed creation', async () => {
  http.getResponse.mockImplementation(readTags);
  http.post.mockRejectedValue({ status_code: 18089 });
  const { unmount } = render(<EditTagsModal isOpen canEditFileTags canReadSpaceTags spaceId="11" fileId="3"
    tagScope={providerScope} onClose={vi.fn()} />, { wrapper: Wrapper });
  await screen.findByText(key('word_create_denied'));
  expect(screen.queryByPlaceholderText(key('new_word_placeholder'))).toBeNull();
  unmount();
  render(<EditTagsModal isOpen canEditFileTags canReadSpaceTags canManageSpaceTags spaceId="11" fileId="3"
    tagScope={providerScope} onClose={vi.fn()} />, { wrapper: Wrapper });
  fireEvent.change(await screen.findByPlaceholderText(key('new_word_placeholder')), { target: { value: 'Reject me' } });
  fireEvent.click(screen.getByRole('button', { name: key('new_word') }));
  // A definite refusal must not be reported as an unknown outcome.
  await screen.findByText(key('rejected'));
  expect(http.post).toHaveBeenCalledOnce(); expect(http.put).not.toHaveBeenCalled();
  expect((screen.getByRole('button', { name: 'com_knowledge.confirm' }) as HTMLButtonElement).disabled).toBe(true);
});
it('reports a refused save as rejected instead of claiming the result is unknown', async () => {
  http.getResponse.mockImplementation(readTags);
  http.put.mockRejectedValue({ status_code: 400 });
  const saved = vi.fn(); openProvider(saved);
  fireEvent.click(await screen.findByRole('button', { name: 'Word 2' }));
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await screen.findByText(key('rejected'));
  expect(screen.queryByText(key('unconfirmed'))).toBeNull();
  expect(saved).not.toHaveBeenCalled();
});
it('explicitly clears with the original revision and blocks a conflicting retry until a fresh review', async () => {
  let serverRevision = 9;
  let serverRefs = [701];
  http.getResponse.mockImplementation((url, opts) => url.includes('/files/') ? envelope(snapshot(serverRefs, serverRevision)) : readTags(url, opts));
  http.put.mockImplementation((_url, command) => {
    if (command.expected_revision !== serverRevision) throw { status_code: 10998 };
    serverRefs = command.tag_ref_ids; return { status_code: 200, data: snapshot(serverRefs, ++serverRevision) };
  });
  const saved = vi.fn(); openProvider(saved);
  await screen.findByRole('button', { name: 'Word 1' });
  serverRefs = [701, 2]; serverRevision = 42;
  fireEvent.click(screen.getByRole('button', { name: key('clear') }));
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await screen.findByText(key('conflict'));
  expect(http.put.mock.calls[0][1]).toEqual({ generation: 4, mode: 'clear', tag_ref_ids: [], expected_revision: 9 });
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  expect(http.put).toHaveBeenCalledTimes(1); expect(saved).not.toHaveBeenCalled(); expect(serverRefs).toEqual([701, 2]);
  fireEvent.click(screen.getByRole('button', { name: key('reload') }));
  const freshWord = await screen.findByRole('button', { name: 'Word 2' });
  expect(freshWord.getAttribute('aria-pressed')).toBe('true');
  expect(http.put).toHaveBeenCalledTimes(1);
});
it('does not start an external list filter or read a Native vocabulary', async () => {
  render(<CompoundSearchInput spaceId="11" tagScope={providerScope} pageMode isRoot />);
  await screen.findByText(key('filter_unavailable')); expect(native.getSpaceTagsApi).not.toHaveBeenCalled();
  expect(http.getResponse).not.toHaveBeenCalled();
});

function DiscoveredEditor({ canEdit = true }: { canEdit?: boolean }) {
  const { tagScope, capabilities } = useSpaceCapabilities('11');
  return <><output>{capabilities.status}</output><EditTagsModal isOpen canEditFileTags={canEdit} canReadSpaceTags spaceId="11" fileId="3" tagScope={tagScope} onClose={vi.fn()} /></>;
}
const capabilities = { provider_key: 'weknora', capability_revision: 2, generation: 4, capabilities: { tag_vocabulary: 'conditional', tag_selection: 'conditional', tag_edit: 'conditional', tag_filter: 'unsupported' } };
it.each(['missing generation', 'old capabilities', 'unknown provider', 'failed lookup'])('never falls back when discovery returns %s', async scenario => {
  http.getResponse.mockImplementation((url: string) => {
    expect(url.endsWith('/capabilities')).toBe(true);
    if (scenario === 'failed lookup') throw new Error('Unavailable');
    return envelope({ ...capabilities, ...(scenario === 'old capabilities' ? { capabilities: {} } : scenario === 'unknown provider' ? { provider_key: 'other' } : { generation: null }) });
  });
  render(<DiscoveredEditor />, { wrapper: Wrapper });
  await screen.findByText(['failed lookup', 'unknown provider'].includes(scenario) ? 'error' : 'success');
  expect(screen.getByText(key('edit_unavailable'))).toBeTruthy();
  expect(native.getSpaceTagsApi).not.toHaveBeenCalled(); expect(http.put).not.toHaveBeenCalled();
});
it.each(['missing contract', 'indeterminate selection', 'wrong generation', 'wrong tenant'])('blocks a save with %s, without using old Native row tags', async scenario => {
  http.getResponse.mockImplementation((url, opts) => {
    if (url.endsWith('/capabilities')) return envelope(capabilities);
    if (!url.includes('/files/')) return readTags(url, opts);
    const data = snapshot([23]);
    return scenario === 'wrong tenant' ? { ...envelope(data), headers: { 'x-management-tenant': '8' } }
      : envelope({ ...data, ...(scenario === 'missing contract' ? { edit_contract: undefined } : scenario === 'wrong generation' ? { generation: 3 } : { tag_ref_ids: null }) });
  });
  render(<DiscoveredEditor />, { wrapper: Wrapper }); await screen.findByText(key('load_failed'));
  expect((screen.getByRole('button', { name: 'com_knowledge.confirm' }) as HTMLButtonElement).disabled).toBe(true);
  expect(native.getSpaceTagsApi).not.toHaveBeenCalled(); expect(http.put).not.toHaveBeenCalled();
});
it.each(['unverified edits', 'no rename grant'])('displays the verified catalog read-only for %s', async scenario => {
  http.getResponse.mockImplementation((url, opts) => url.endsWith('/capabilities') ? envelope({ ...capabilities,
    capabilities: { ...capabilities.capabilities, tag_edit: scenario === 'unverified edits' ? 'unverified' : 'conditional' } }) : readTags(url, opts));
  render(<DiscoveredEditor canEdit={scenario !== 'no rename grant'} />, { wrapper: Wrapper });
  const word = await screen.findByRole('button', { name: 'Word 1' });
  expect((word as HTMLButtonElement).disabled).toBe(true); expect(screen.getByText(key('read_only'))).toBeTruthy();
  expect(native.getSpaceTagsApi).not.toHaveBeenCalled();
});
it('never requests Native tags from either real entry without a verified Native route', async () => {
  render(<><CompoundSearchInput spaceId="11" tagScope={unavailable} isRoot pageMode />
    <EditTagsModal isOpen spaceId="11" fileId="3" tagScope={unavailable} initialTagIds={[4]} onClose={vi.fn()} /></>, { wrapper: Wrapper });
  await screen.findByText(key('filter_unavailable')); await screen.findByText(key('edit_unavailable'));
  expect(native.getSpaceTagsApi).not.toHaveBeenCalled(); expect(http.getResponse).not.toHaveBeenCalled();
});
it('keeps a Native list filter on both the first and last pages of a 550-word dictionary', async () => {
  const search = vi.fn();
  render(<CompoundSearchInput spaceId="11" tagScope={nativeScope} isRoot pageMode onSearch={search} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Word 1' }));
  expect(screen.queryByText('Word 550')).toBeNull();
  while (!screen.queryByText('Word 550')) fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.move_next_page' }));
  fireEvent.click(screen.getByRole('button', { name: 'Word 550' }));
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.move_previous_page' }));
  expect(search).toHaveBeenLastCalledWith({ scope: 'all', tagIds: [1, 550], keyword: '' });
});
it('preserves Native edit selections while paging and saves Native IDs through the original endpoint', async () => {
  render(<EditTagsModal isOpen spaceId="11" fileId="3" tagScope={nativeScope} initialTagIds={[1]} onClose={vi.fn()} />, { wrapper: Wrapper });
  await screen.findAllByText('Word 1'); expect(screen.queryByText('Word 550')).toBeNull();
  while (!screen.queryByText('Word 550')) fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.move_next_page' }));
  fireEvent.click(screen.getByText('Word 550'));
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.move_previous_page' }));
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await vi.waitFor(() => expect(native.updateFileTagsApi).toHaveBeenCalledWith('11', '3', [1, 550]));
  expect(http.put).not.toHaveBeenCalled();
});
