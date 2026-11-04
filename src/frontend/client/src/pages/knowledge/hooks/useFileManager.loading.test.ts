import { act, renderHook, waitFor } from '@testing-library/react';
import type { KnowledgeSpace } from '~/api/knowledge';
import { getSpaceChildrenApi } from '~/api/knowledge';
import { useFileManager } from './useFileManager';

jest.mock('~/api/knowledge', () => ({
  SPACE_CHILDREN_DEFAULT_PAGE_SIZE: 40,
  getSpaceChildrenApi: jest.fn(),
  getFolderParentPathApi: jest.fn(async () => []),
  searchSpaceChildrenApi: jest.fn(),
}));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('../knowledgeUtils', () => ({ isKnowledgeItemPending: () => false }));
jest.mock('~/common', () => ({ NotificationSeverity: { WARNING: 'warning' } }));

const load = jest.mocked(getSpaceChildrenApi);
const space = (id: string, role?: string) => ({ id, name: id, role } as KnowledgeSpace);
beforeEach(() => {
  load.mockReset();
  load.mockResolvedValue({ data: [{ id: 'file-1', name: 'File' }], has_more: false, next_cursor: null } as Awaited<ReturnType<typeof getSpaceChildrenApi>>);
});

it('keeps loaded files and avoids a second loading cycle when role details arrive', async () => {
  const { result, rerender } = renderHook(({ activeSpace }) => useFileManager({ activeSpace }), {
    initialProps: { activeSpace: space('one', 'member') },
  });
  await waitFor(() => expect(result.current.files).toHaveLength(1));
  expect(load).toHaveBeenCalledTimes(1);
  load.mockImplementation(() => new Promise(() => {}));
  rerender({ activeSpace: space('one', 'admin') });
  expect(load).toHaveBeenCalledTimes(1);
  expect(result.current.files).toHaveLength(1);
  expect(result.current.loading).toBe(false);
});

it('waits for initial role details and still loads a different space', async () => {
  const { result, rerender } = renderHook(({ activeSpace }) => useFileManager({ activeSpace }), {
    initialProps: { activeSpace: space('one') },
  });
  expect(load).not.toHaveBeenCalled();
  rerender({ activeSpace: space('one', 'member') });
  await waitFor(() => expect(result.current.files).toHaveLength(1));
  rerender({ activeSpace: space('two', 'member') });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(load).toHaveBeenCalledTimes(2);
  expect(load).toHaveBeenLastCalledWith(expect.objectContaining({ space_id: 'two' }));
});

it('still reloads when the user opens another folder', async () => {
  const activeSpace = space('one', 'member');
  const { result, rerender } = renderHook(({ initialFolderId }: { initialFolderId?: string }) => useFileManager({ activeSpace, initialFolderId }), { initialProps: {} });
  await waitFor(() => expect(result.current.files).toHaveLength(1));
  act(() => rerender({ initialFolderId: 'folder-2' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(load).toHaveBeenCalledTimes(2);
  expect(load).toHaveBeenLastCalledWith(expect.objectContaining({ parent_id: 'folder-2' }));
});
