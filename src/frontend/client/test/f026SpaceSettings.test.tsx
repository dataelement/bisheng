import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { KnowledgeSpaceSettingsPage } from '~/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage';

const http = vi.hoisted(() => ({ scope: vi.fn(), get: vi.fn(), getResponse: vi.fn(), post: vi.fn(), put: vi.fn() }));
const page = vi.hoisted(() => ({ id: undefined as string | undefined, navigate: vi.fn(), toast: vi.fn() }));
vi.mock('~/api/request', () => ({ default: http, prepareBrowserHeaders: http.scope, showApiError: vi.fn() }));
vi.mock('react-router-dom', () => ({ useNavigate: () => page.navigate, useParams: () => ({ spaceId: page.id }), useLocation: () => ({ state: null }) }));
vi.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: null }) }));
vi.mock('~/hooks/useSelectCopy', () => ({ default: () => ({}) }));
vi.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: page.toast }), useConfirm: () => vi.fn() }));
vi.mock('~/utils', () => ({ generateUUID: () => 'stable-request-key', getFullWidthLength: (s: string) => s.length, truncateByFullWidth: (s: string) => s, cn: (...xs: string[]) => xs.join(' ') }));
vi.mock('~/components/ModuleHome', () => ({ MODULE_PAGE_DESKTOP_COLUMN: '', MODULE_PAGE_DESKTOP_FRAME: '' }));
vi.mock('~/components/permission/PermissionDraftPanel', () => ({ PermissionDraftPanel: () => null }));
vi.mock('~/components/permission/PermissionDraftPickerDialog', () => ({ PermissionDraftPickerDialog: () => null }));

const path = '/api/v1/knowledge/space';
const preset = { type: 'document', model_policy: 'bisheng-v1', preset_revision: 3, summary_model_id: 'chat-prod', summary_version: 'v7', embedding_model_id: 'embed-prod', embedding_version: 'v3', embedding_dimension: 768, vision_model_id: 'vision-prod', vision_version: 'v4', wiki_model_id: null, tag_model_id: null, chunk_size: 512, overlap: 0, vector_index_enabled: true, keyword_index_enabled: true, wiki_enabled: true, entities_enabled: true, multimodal_enabled: true, auto_tag_enabled: true };
const rawSpace = { id: 12, name: 'Docs', description: 'before', auth_type: 'approval', is_released: true, auto_tag_enabled: true, auto_tag_custom_tags: ['keep'] };
const envelope = (data: unknown) => ({ status_code: 200, data });
let provider: string;
let actions: string[];
function open(id?: string) {
  page.id = id;
  render(<QueryClientProvider client={new QueryClient()}><KnowledgeSpaceSettingsPage /></QueryClientProvider>);
}
const nameInput = () => screen.findByPlaceholderText('com_subscription.enter_knowledge_space_name');
const create = () => screen.getByRole<HTMLButtonElement>('button', { name: 'com_unified_permission.confirm_create' });
async function selectExternal() {
  open();
  fireEvent.change(await nameInput(), { target: { value: 'Atlas' } });
  fireEvent.click(screen.getByRole('radio', { name: /weknora/i }));
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
  http.scope.mockResolvedValue({ 'X-Management-Tenant': '23' });
  provider = 'weknora'; actions = ['visible'];
  http.get.mockImplementation(async (url: string) => {
    if (url.endsWith('/creation-permission-context')) return envelope({ grantable_models: [], can_configure_initial_permissions: false });
    if (url.endsWith('/auto-tag-visibility')) return envelope({ visible: false });
    if (url.endsWith('/my-permissions')) return envelope({ actions });
    if (url.endsWith('/context')) return envelope({ can_manage_permission: true, resource_version: 1, catalog_release_id: 1 });
    if (url.endsWith('/grantable-models')) return envelope([]);
    if (url.endsWith('/grants')) return envelope({ data: [], has_more: false });
    if (url.endsWith('/info')) return envelope(rawSpace);
    if (url.endsWith('/capabilities')) return envelope({ provider_key: provider, capability_revision: 3, capabilities: { settings_write: 'unverified' } });
    if (url.endsWith('/settings')) return envelope({ revision: 2, pending: null, settings: { ...preset, wiki_model_id: 'wiki-override' } });
    throw new Error(`Unexpected GET ${url}`);
  });
  http.getResponse.mockResolvedValue({ headers: { 'x-management-tenant': '23' }, data: envelope(preset) });
  http.post.mockResolvedValue(envelope({ operation_id: 'op-1', space_id: 12, state: 'pending' }));
  http.put.mockResolvedValue(envelope(rawSpace));
});
afterEach(cleanup);

it('submits the displayed verified preset, sharing and pinned tenant; an operation receipt is not a ready space', async () => {
  await selectExternal();
  await screen.findByText(/chat-prod/);
  for (const value of ['embed-prod', '768', 'vision-prod', '512', 'v7', 'v3', 'v4']) expect(document.body.textContent).toContain(value);
  expect(http.getResponse).toHaveBeenCalledWith(`${path}/creation-settings`, { params: { provider_key: 'weknora' } });
  fireEvent.click(create());
  await waitFor(() => expect(http.post).toHaveBeenCalledWith(path, {
    name: 'Atlas', description: '', auth_type: 'approval', is_released: true, provider_key: 'weknora', creation_request_id: 'stable-request-key', preset_summary: preset,
  }, { headers: { 'X-Management-Tenant': '23' } }));
  await waitFor(() => expect(page.navigate).toHaveBeenCalledWith('/knowledge'));
  expect(page.toast).not.toHaveBeenCalledWith(expect.objectContaining({ message: 'com_knowledge.space_create_success' }));
});
it.each([{ embedding_dimension: 0 }, { vision_version: '' }, { summary_model_id: '' }, { overlap: 512 }, { model_policy: 'other' }])('blocks a malformed preset %j without Native fallback', async invalid => {
  http.getResponse.mockResolvedValue({ headers: { 'x-management-tenant': '23' }, data: envelope({ ...preset, ...invalid }) });
  await selectExternal();
  await screen.findByRole('alert');
  expect(create().disabled).toBe(true); fireEvent.click(create()); expect(http.post).not.toHaveBeenCalled();
});
it.each([['visible'], ['visible', 'edit'], ['visible', 'edit', 'manage_permission']])('opens authorized external readback, never posts unverified settings (%s)', async (...rights) => {
  actions = rights;
  open('12');
  await screen.findByText(/wiki-override/);
  expect((await nameInput() as HTMLInputElement).disabled).toBe(true);
  expect(screen.getByRole<HTMLButtonElement>('button', { name: 'com_unified_permission.save' }).disabled).toBe(true);
  expect(http.get).toHaveBeenCalledWith(`${path}/12/settings`);
  expect(http.put).not.toHaveBeenCalled();
});
it.each([true, false])('saves a Native description without unpublishing or writing tags (visible=%s)', async visible => {
  if (visible) {
    const original = http.get.getMockImplementation()!;
    http.get.mockImplementation((url: string) => url.endsWith('/auto-tag-visibility') ? envelope({ visible: true }) : url.endsWith('/tag-libraries') ? envelope({ data: [] }) : original(url));
  }
  provider = 'native'; actions = ['edit', 'visible']; open('12');
  const description = await screen.findByDisplayValue('before');
  fireEvent.change(description, { target: { value: 'after' } });
  fireEvent.click(screen.getByRole('button', { name: 'com_unified_permission.save' }));
  await waitFor(() => expect(http.put).toHaveBeenCalledWith(`${path}/12`, { description: 'after' }));
  expect(http.get).not.toHaveBeenCalledWith(`${path}/12/settings`);
});

it('does not send a previous tenant’s reviewed preset', async () => {
  http.scope.mockResolvedValue({ 'X-Management-Tenant': '24' });
  await selectExternal(); await screen.findByText(/chat-prod/); fireEvent.click(create());
  await waitFor(() => expect(http.scope).toHaveBeenCalledWith('POST', path));
  expect(http.post).not.toHaveBeenCalled(); expect(page.navigate).not.toHaveBeenCalled();
});
it('does not expose reads or writes without a matching space permission', async () => {
  actions = []; open('12'); await screen.findByRole('alert');
  expect(http.get).not.toHaveBeenCalledWith(`${path}/12/settings`);
  expect(screen.queryByRole('button', { name: 'com_unified_permission.save' })).toBeNull();
  expect(http.put).not.toHaveBeenCalled();
});
it.each(['unreachable', 'missing tenant'])('blocks unverified environment (%s) without falling back', async problem => {
  if (problem === 'unreachable') http.getResponse.mockRejectedValue(new Error('Probe failed'));
  else http.getResponse.mockResolvedValue({ headers: {}, data: envelope(preset) });
  await selectExternal(); await screen.findByRole('alert');
  fireEvent.click(create()); expect(http.post).not.toHaveBeenCalled();
});
it('rejects unknown capabilities before showing a Native editor', async () => {
  provider = 'other'; actions = ['visible', 'edit']; open('12'); await screen.findByRole('alert');
  expect(http.get).not.toHaveBeenCalledWith(`${path}/12/settings`);
  expect(screen.queryByPlaceholderText('com_subscription.enter_knowledge_space_name')).toBeNull();
  expect(http.put).not.toHaveBeenCalled();
});
it('sends the selected private access mode without initial grants', async () => {
  const original = http.get.getMockImplementation()!;
  http.get.mockImplementation((url: string) => url.endsWith('/creation-permission-context')
    ? envelope({ grantable_models: [], can_configure_initial_permissions: true, catalog_release_id: 1 }) : original(url));
  await selectExternal(); await screen.findByText(/chat-prod/);
  fireEvent.click(screen.getByRole('radio', { name: /com_unified_permission.private/ }));
  fireEvent.click(create()); await waitFor(() => expect(http.post).toHaveBeenCalledTimes(1));
  const [, body] = http.post.mock.calls[0];
  expect(body).toMatchObject({ auth_type: 'private', is_released: false });
  expect(body).not.toHaveProperty('initial_permissions'); expect(body).not.toHaveProperty('auto_tag_enabled');
});
it('preserves default Native creation and its ready-space response', async () => {
  http.post.mockResolvedValue(envelope(rawSpace)); open();
  fireEvent.change(await nameInput(), { target: { value: 'Native' } }); fireEvent.click(create());
  await waitFor(() => expect(page.navigate).toHaveBeenCalledWith('/knowledge/space/12'));
  expect(http.getResponse).not.toHaveBeenCalled();
  expect(http.post).toHaveBeenCalledWith(path, { name: 'Native', description: '', auth_type: 'approval', is_released: true, creation_request_id: 'stable-request-key', auto_tag_enabled: false, auto_tag_library_id: null, auto_tag_custom_tags: null });
});
