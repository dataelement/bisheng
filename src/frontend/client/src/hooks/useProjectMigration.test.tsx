import type { PropsWithChildren } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { migrateLegacyProjects, useProjectMigration } from './useProjectMigration';
import type { ProjectActionResult, ProjectOperation } from '~/api/chatProjects';

const identity = 'http://test:1:7';
const sourceId = '11111111-1111-4111-8111-111111111111';
const mockMutateAsync = jest.fn();
jest.mock('~/api/chatProjects', () => ({ newProjectRequestId: () => '11111111-1111-4111-8111-111111111111' }));
jest.mock('./useChatProjects', () => ({
  useProjectIdentity: () => 'http://test:1:7',
  useChatProjects: () => ({ isSuccess: true }),
  useChatProjectActions: () => ({ mutateAsync: mockMutateAsync }),
}));
const result: ProjectActionResult = { revision: '1', applied_revision: '1', replayed: false, notification: 'live', outcome: { items: [] } };
function legacy(count = 1, members = 1) {
  localStorage.setItem('bs_mock_projects', JSON.stringify(Array.from({ length: count }, (_, i) => ({ id: `old-${i}`, name: `Project ${i}` }))));
  localStorage.setItem('bs_mock_project_chats', JSON.stringify(Object.fromEntries(Array.from({ length: members }, (_, i) => [`chat-${i}`, 'old-0']))));
}
beforeEach(() => { localStorage.clear(); mockMutateAsync.mockReset().mockResolvedValue(result); });

it('starts automatically after authentication without a migration action', async () => {
  legacy();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const hook = renderHook(() => useProjectMigration(), { wrapper });
  await waitFor(() => expect(localStorage.getItem(`bs_project_import_done_v1:${identity}`)).toBe(sourceId));
  expect(mockMutateAsync).toHaveBeenCalledTimes(2);
  expect(mockMutateAsync.mock.calls[0][0].operation).toMatchObject({ operation: 'import', projects: [{ legacy_id: 'old-0', name: 'Project 0' }] });
  hook.unmount(); client.clear();
});

it('saves every project mapping before member batches and retains the original records', async () => {
  legacy(101, 501);
  const original = localStorage.getItem('bs_mock_projects');
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>().mockResolvedValue(result);
  await migrateLegacyProjects(identity, perform, () => true);
  expect(perform.mock.calls.map(([operation]) => operation.operation === 'import' ? [operation.projects.length, operation.memberships.length] : [])).toEqual([[100, 0], [1, 0], [0, 500], [0, 1]]);
  expect(localStorage.getItem('bs_mock_projects')).toBe(original);
});

it('reuses its source identity after an uncertain failure and skips completed migrations', async () => {
  legacy();
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>().mockRejectedValueOnce(new Error('response lost')).mockResolvedValue(result);
  await expect(migrateLegacyProjects(identity, perform, () => true)).rejects.toThrow('response lost');
  expect(localStorage.getItem(`bs_project_import_done_v1:${identity}`)).toBeNull();
  await migrateLegacyProjects(identity, perform, () => true);
  expect(perform.mock.calls.every(([operation]) => operation.operation === 'import' && operation.source_client_id === sourceId)).toBe(true);
  perform.mockClear();
  await migrateLegacyProjects(identity, perform, () => true);
  expect(perform).not.toHaveBeenCalled();
});

it('stops on identity changes and never adopts another account’s legacy records', async () => {
  legacy(101);
  let current = true;
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>(async () => { current = false; return result; });
  await expect(migrateLegacyProjects(identity, perform, () => current)).rejects.toThrow('Identity changed');
  expect(perform).toHaveBeenCalledTimes(1);
  perform.mockClear();
  await migrateLegacyProjects('http://test:1:8', perform, () => true);
  expect(perform).not.toHaveBeenCalled();
  expect(localStorage.getItem(`bs_project_import_done_v1:${identity}`)).toBeNull();
});

it('reports corrupt entries while migrating valid history without blocking the batch', async () => {
  legacy();
  localStorage.setItem('bs_mock_project_chats', JSON.stringify({ 'chat-0': 'old-0', '../invalid': 'old-0', new: 'old-0' }));
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>().mockResolvedValue(result);
  const status = await migrateLegacyProjects(identity, perform, () => true);
  expect(status).toMatchObject({ phase: 'done', skipped: 2 });
  expect(perform.mock.calls[1][0]).toMatchObject({ memberships: [{ chat_id: 'chat-0', legacy_project_id: 'old-0' }] });
});

it('retries automatically after a transport failure without asking the user to start again', async () => {
  jest.useFakeTimers();
  legacy();
  mockMutateAsync.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(result);
  jest.spyOn(console, 'warn').mockImplementation(() => {});
  const client = new QueryClient();
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const hook = renderHook(() => useProjectMigration(), { wrapper });
  try {
    await act(async () => {});
    expect(localStorage.getItem(`bs_project_import_done_v1:${identity}`)).toBeNull();
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(localStorage.getItem(`bs_project_import_done_v1:${identity}`)).toBe(sourceId);
  } finally { hook.unmount(); client.clear(); jest.useRealTimers(); }
});
