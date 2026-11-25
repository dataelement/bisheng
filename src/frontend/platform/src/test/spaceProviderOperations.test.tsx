import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SpaceManagementView } from '@/pages/KnowledgePage/components/SpaceManagementView';
import { userContext } from '@/contexts/userContext';
import type { KnowledgeQueryScope } from '@/controllers/hooks/knowledge';
import type { User } from '@/types/api/user';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), permissions: vi.fn() }));
vi.mock('@/controllers/request', () => ({ default: api, showApiError: vi.fn() }));
vi.mock('@/controllers/API/permission', () => ({ getMyResourcePermissionsApi: api.permissions }));
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: {} }) }));
const path = '/api/v1/knowledge/space/7/provider-operations';
const scope: KnowledgeQueryScope = { view: 'admin', identityKey: 'user:4', tenantId: 31, managementTenantId: 31 };
const admin = { user_id: 4, is_child_admin: true, leaf_tenant_id: 31 };
const row = {
  operation_id: 'ef802bb2-e0b9-4a95-9f74-13dfaa5cd863', kind: 'upload',
  space_id: 7, version_ids: [4201], remote_target: 'target-abcdef0123456789', generation: 17,
  phase: 'upload', attempt: 3, state: 'pending', error_code: null, capability_revision: 42,
  capability_state: 'unknown', manual_release_allowed: false, create_time: '2026-11-19T10:00:00',
  body: 'private document', remote_task_id: 'secret-task-token',
};
const clients: QueryClient[] = [];
function mount(user: Partial<User> = admin, active = scope, tenant: number | null = 31) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  function tree(u: Partial<User>, s: KnowledgeQueryScope, t: number | null) {
    const info = { id: 7, name: 'Reports', tenant_id: t };
    return <QueryClientProvider client={client}><MemoryRouter><userContext.Provider value={{ user: u, setUser: vi.fn(), savedComponents: [], addSavedComponent: async () => undefined, checkComponentsName: () => false, delComponent: vi.fn() }}>
      <SpaceManagementView scope={s} spaceId={7} spaceInfo={info} parentId={null}>{() => <span>directory</span>}</SpaceManagementView>
    </userContext.Provider></MemoryRouter></QueryClientProvider>;
  }
  const view = render(tree(user, active, tenant));
  return { client, switchTo: (u: Partial<User>, s: KnowledgeQueryScope, t = tenant) => view.rerender(tree(u, s, t)) };
}
async function menu() {
  fireEvent.keyDown(await screen.findByRole('button', { name: 'more' }), { key: 'Enter' });
  return within(await screen.findByRole('menu'));
}
async function open() {
  fireEvent.click(await (await menu()).findByRole('menuitem', { name: 'detail.view_task_records' }));
  return within(await screen.findByRole('dialog', { name: 'detail.task_records' }));
}
beforeEach(() => {
  vi.resetAllMocks();
  api.permissions.mockResolvedValue({ actions: ['edit', 'visible'] });
  api.get.mockImplementation(async (url, { params }) => {
    if (url.endsWith('/processing-jobs')) return { data: [], total: 0 };
    if (url === path) return { data: [params.page === 1 ? row : { ...row, generation: 12, state: 'failed', error_code: 'not_received' }], total: 21 };
    throw new Error('Unexpected GET');
  });
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });

it.each([admin, { user_id: 4, is_global_super: true, leaf_tenant_id: 1 }])('reads original targets on demand, pages across generations, never offers release (%j)', async (user) => {
  mount(user);
  expect(api.get.mock.calls.some(([url]) => url === path)).toBe(false);
  const dialog = await open();
  expect(await dialog.findByText('4201')).toBeVisible();
  for (const text of [row.remote_target, '17', '3', 'provider_operations.states.pending', 'provider_operations.phases.upload', 'provider_operations.unverified']) expect(dialog.getByText(text)).toBeVisible();
  expect(dialog.queryByText(/private document|secret-task-token/)).toBeNull();
  expect(dialog.queryByRole('button', { name: /release|retry|approve/i })).toBeNull();
  fireEvent.click(dialog.getByRole('button', { name: 'pagination.next' }));
  expect(await dialog.findByText('12')).toBeVisible();
  expect(dialog.queryByText('17')).toBeNull();
  expect(dialog.getByText('provider_operations.errors.not_received')).toBeVisible();
  expect(dialog.getByText('provider_operations.states.failed')).toBeVisible();
  expect(api.get).toHaveBeenCalledWith(path, expect.objectContaining({ params: { page: 2, page_size: 20 } }));
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
});

it.each([
  [{ user_id: 4 }, scope, 31], [admin, { ...scope, view: 'ordinary' }, 31],
  [admin, { ...scope, identityKey: 'user:5' }, 31], [admin, scope, 32],
  [admin, { ...scope, managementTenantId: null }, 31], [admin, scope, null],
  [{ ...admin, leaf_tenant_id: 32 }, scope, 31],
] as const)('does not expose diagnostics for mismatched or unverified authority (%j, %j, %j)', async (u, s, tenant) => {
  const view = mount(u, s, tenant);
  await waitFor(() => expect(view.client.isFetching()).toBe(0));
  expect((await menu()).queryByRole('menuitem', { name: 'detail.view_task_records' })).toBeNull();
  expect(api.get.mock.calls.some(([url]) => url === path)).toBe(false);
});

it('denies the diagnostic entry to an administrator without the space edit action', async () => {
  api.permissions.mockResolvedValue({ actions: ['visible', 'manage_permission'] });
  mount();
  expect((await menu()).queryByRole('menuitem', { name: 'detail.view_task_records' })).toBeNull();
  expect(api.get.mock.calls.some(([url]) => url === path)).toBe(false);
});

it('drops in-flight diagnostics when the identity is replaced', async () => {
  let resolve!: (value: unknown) => void;
  const fallback = api.get.getMockImplementation()!;
  api.get.mockImplementation((url, opts) => url === path ? new Promise(r => { resolve = r; }) : fallback(url, opts));
  const view = mount(); await open();
  await waitFor(() => expect(resolve).toBeDefined());
  view.switchTo({ user_id: 5 }, { ...scope, identityKey: 'user:5' });
  await act(async () => resolve({ data: [row], total: 1 }));
  expect(screen.queryByText('4201')).toBeNull();
  expect(screen.queryByRole('dialog')).toBeNull();
});

it('closes a loaded page on a management-tenant switch and opens the new scope at page one', async () => {
  const superAdmin = { user_id: 4, is_global_super: true };
  let currentVersion = 4201;
  const fallback = api.get.getMockImplementation()!;
  api.get.mockImplementation((url, opts) => url === path ? Promise.resolve({ total: 21, data: [{ ...row, version_ids: [currentVersion] }] }) : fallback(url, opts));
  const view = mount(superAdmin);
  const first = await open();
  await first.findByText('4201');
  fireEvent.click(first.getByRole('button', { name: 'pagination.next' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledWith(path, expect.objectContaining({ params: { page: 2, page_size: 20 } })));
  currentVersion = 6202;
  view.switchTo(superAdmin, { ...scope, tenantId: 32, managementTenantId: 32 }, 32);
  expect(screen.queryByRole('dialog')).toBeNull();
  const second = await open();
  expect(await second.findByText('6202')).toBeVisible();
  expect(second.queryByText('4201')).toBeNull();
  expect(api.get.mock.calls.filter(([url]) => url === path).map(([, opts]) => opts.params.page)).toEqual([1, 2, 1]);
});

it('does not render unrecognized identifiers, free text, or upstream action claims', async () => {
  const fallback = api.get.getMockImplementation()!;
  const untrusted = { ...row, remote_target: 'private://host/body?credential=secret', phase: 'private-phase', kind: 'private-kind',
    operation_id: 'private-operation', error_code: 'private-error', capability_state: 'supported', manual_release_allowed: true, state: 'manual_review' };
  api.get.mockImplementation((url, opts) => url === path ? Promise.resolve({ data: [untrusted], total: 1 }) : fallback(url, opts));
  mount(); const dialog = await open();
  expect(await dialog.findByText('provider_operations.states.manual_review')).toBeVisible();
  expect(dialog.getByText('provider_operations.unverified')).toBeVisible();
  expect(dialog.getByText('provider_operations.phases.unknown')).toBeVisible();
  expect(dialog.queryByText(/private|credential|supported/)).toBeNull();
  expect(dialog.queryByRole('button', { name: /release|approve|retry/i })).toBeNull();
});

it('keeps a failed read distinct from an empty history and retries only the GET', async () => {
  const fallback = api.get.getMockImplementation()!;
  let tries = 0;
  api.get.mockImplementation((url, opts) => url !== path ? fallback(url, opts) : ++tries === 1 ? Promise.reject(new Error('private upstream failure')) : Promise.resolve({ data: [], total: 0 }));
  mount(); const dialog = await open();
  expect(await dialog.findByRole('alert')).toHaveTextContent('provider_operations.unavailable');
  expect(dialog.queryByText(/private upstream failure|provider_operations.empty/)).toBeNull();
  fireEvent.click(dialog.getByRole('button', { name: 'retry' }));
  expect(await dialog.findByText('provider_operations.empty')).toBeVisible();
  expect(tries).toBe(2);
});
