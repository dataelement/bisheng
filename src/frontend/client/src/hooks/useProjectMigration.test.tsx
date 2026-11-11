import type { PropsWithChildren } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { migrateLegacyProjects, useProjectMigration } from './useProjectMigration';
import type { ProjectActionResult, ProjectOperation } from '~/api/chatProjects';

const identity = 'http://test:1:7';
const mockMutateAsync = jest.fn();
jest.mock('./useChatProjects', () => ({
  useProjectIdentity: () => 'http://test:1:7',
  useChatProjects: () => ({ isSuccess: true }),
  useChatProjectActions: () => ({ mutateAsync: mockMutateAsync }),
}));
const result: ProjectActionResult = { outcome: { items: [] } };
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
  await waitFor(() => expect(localStorage.getItem(`bs_project_import_done_v2:${identity}`)).toBe('1'));
  expect(mockMutateAsync).toHaveBeenCalledTimes(1);
  expect(mockMutateAsync.mock.calls[0][0].operation).toMatchObject({ operation: 'import', projects: [{ legacy_id: 'old-0', name: 'Project 0' }] });
  hook.unmount(); client.clear();
});

it('sends the whole legacy record in one request, capped at the server limits, and keeps the originals', async () => {
  legacy(101, 2001);
  const original = localStorage.getItem('bs_mock_projects');
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>().mockResolvedValue(result);
  const status = await migrateLegacyProjects(identity, perform, () => true);
  expect(perform).toHaveBeenCalledTimes(1);
  const [operation] = perform.mock.calls[0];
  expect(operation.operation === 'import' && [operation.projects.length, operation.memberships.length]).toEqual([100, 2000]);
  expect(status.skipped).toBe(2);
  expect(localStorage.getItem('bs_mock_projects')).toBe(original);
});

it('retries after an uncertain failure and skips a completed migration', async () => {
  legacy();
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>().mockRejectedValueOnce(new Error('response lost')).mockResolvedValue(result);
  await expect(migrateLegacyProjects(identity, perform, () => true)).rejects.toThrow('response lost');
  expect(localStorage.getItem(`bs_project_import_done_v2:${identity}`)).toBeNull();
  await migrateLegacyProjects(identity, perform, () => true);
  perform.mockClear();
  await migrateLegacyProjects(identity, perform, () => true);
  expect(perform).not.toHaveBeenCalled();
});

it('lets every account in the same browser import its own share; the server decides ownership', async () => {
  legacy();
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>().mockResolvedValue({ outcome: { items: [{ kind: 'project', legacy_id: 'old-0', status: 'not_owned' }] } });
  await migrateLegacyProjects(identity, perform, () => true);
  const other = await migrateLegacyProjects('http://test:1:8', perform, () => true);
  expect(perform).toHaveBeenCalledTimes(2);
  expect(other).toMatchObject({ phase: 'done', skipped: 1, details: [{ id: 'old-0', status: 'not_owned' }] });
});

it('ignores a late result after the identity changed', async () => {
  legacy();
  let current = true;
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>(async () => { current = false; return result; });
  await expect(migrateLegacyProjects(identity, perform, () => current)).rejects.toThrow('Identity changed');
  expect(localStorage.getItem(`bs_project_import_done_v2:${identity}`)).toBeNull();
});

it('reports corrupt entries while migrating valid history without blocking the batch', async () => {
  legacy();
  localStorage.setItem('bs_mock_project_chats', JSON.stringify({ 'chat-0': 'old-0', '../invalid': 'old-0', new: 'old-0' }));
  const perform = jest.fn<Promise<ProjectActionResult>, [ProjectOperation]>().mockResolvedValue(result);
  const status = await migrateLegacyProjects(identity, perform, () => true);
  expect(status).toMatchObject({ phase: 'done', skipped: 2 });
  expect(perform.mock.calls[0][0]).toMatchObject({ memberships: [{ chat_id: 'chat-0', legacy_project_id: 'old-0' }] });
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
    expect(localStorage.getItem(`bs_project_import_done_v2:${identity}`)).toBeNull();
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(localStorage.getItem(`bs_project_import_done_v2:${identity}`)).toBe('1');
  } finally { hook.unmount(); client.clear(); jest.useRealTimers(); }
});
