import { act, renderHook, waitFor } from '@testing-library/react';
import { FileStatus, FileType, SpaceRole, getSpaceChildrenApi, type KnowledgeFile, type KnowledgeSpace } from '~/api/knowledge';
import { useFileManager } from './useFileManager';

const mockLocalize = (key: string) => key;
jest.mock('~/hooks', () => ({ useLocalize: () => mockLocalize }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/api/knowledge', () => ({ ...jest.requireActual('~/api/knowledge'), getSpaceChildrenApi: jest.fn() }));
const file = (id: string): KnowledgeFile => ({ id, name: id, type: FileType.PDF, status: FileStatus.SUCCESS, tags: [], path: '', spaceId: '3', createdAt: '', updatedAt: '' });
it('preserves fetched page boundaries and starts a new permission epoch on refresh', async () => {
    jest.mocked(getSpaceChildrenApi).mockResolvedValueOnce({ data: [file('11')], has_more: true, next_cursor: 'next' } as never)
        .mockResolvedValueOnce({ data: [file('12')], has_more: false } as never)
        .mockResolvedValue({ data: [file('11')], has_more: false } as never);
    const space = { id: '3', name: 'Space', role: SpaceRole.MEMBER } as KnowledgeSpace;
    const { result } = renderHook(() => useFileManager({ activeSpace: space }));
    await waitFor(() => expect(result.current.files).toHaveLength(1));
    expect(result.current.downloadPages).toEqual([['11']]);
    const epoch = result.current.downloadEpoch;
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.files).toHaveLength(2));
    expect(result.current.downloadPages).toEqual([['11'], ['12']]);
    expect(result.current.downloadEpoch).toBe(epoch);
    await act(async () => { await result.current.loadFiles(1); });
    expect(result.current.downloadPages).toEqual([['11']]);
    expect(result.current.downloadEpoch).toBeGreaterThan(epoch);
});
