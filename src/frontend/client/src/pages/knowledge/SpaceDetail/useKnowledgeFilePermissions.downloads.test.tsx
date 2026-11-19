import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FileStatus, FileType, SpaceRole, type KnowledgeFile, type KnowledgeSpace } from '~/api/knowledge';
import request, { showApiError } from '~/api/request';
import { getMyResourcePermissions } from '~/api/permission';
import type { BatchInspection } from '~/api/knowledgeBatch';
import { useKnowledgeFilePermissions } from './useKnowledgeFilePermissions';
import { useKnowledgeSelectionActions } from './useKnowledgeSelectionActions';
import type { UseKnowledgeFilePermissionsOptions } from './knowledgeSpaceTypes';

let mockUser = { id: '7', role: 'member', tenant_id: 101 };
jest.mock('~/hooks', () => ({ useAuthContext: () => ({ user: mockUser }) }));
jest.mock('~/api/request', () => ({ __esModule: true, default: { postResponse: jest.fn() }, showApiError: jest.fn() }));
jest.mock('~/api/permission', () => ({ getMyResourcePermissions: jest.fn() }));

type Options = UseKnowledgeFilePermissionsOptions & { downloadPages?: string[][]; downloadEpoch?: number };
const file = (id: string, type = FileType.PDF): KnowledgeFile => ({
    id, name: `${id}.pdf`, type, status: FileStatus.SUCCESS, tags: [], path: '', spaceId: '3', createdAt: '', updatedAt: '',
});
const space = { id: '3', name: 'Space', role: SpaceRole.MEMBER } as KnowledgeSpace;
const inspection = (ids: number[], complete = true, folders: number[] = []): BatchInspection => ({
    check_complete: complete, can_execute: ids.length + folders.length > 0,
    valid_items: [...ids.map(id => ({ id, type: 'file' as const, name: null })), ...folders.map(id => ({ id, type: 'folder' as const, name: null }))],
    invalid_items: [], requires_skip_confirmation: false, impact: {},
});
const response = (data: BatchInspection) => ({
    headers: { 'x-management-tenant': '101' }, data: { status_code: 200, status_message: 'ok', data },
});
function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>(yes => { resolve = yes; });
    return { promise, resolve };
}
const clients: QueryClient[] = [];
function mount(options: Partial<Options> = {}) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } }, logger: { log: jest.fn(), warn: jest.fn(), error: jest.fn() } });
    clients.push(client);
    const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const initialProps: Options = { space, currentFolderId: undefined, displayFiles: [file('11')], downloadPages: [['11']], downloadEpoch: 1, ...options };
    return renderHook((props: Options) => {
        const permissions = useKnowledgeFilePermissions(props);
        const [selectedFiles, setSelectedFiles] = React.useState(new Set<string>());
        const noop = () => undefined;
        const selection = useKnowledgeSelectionActions({
            displayFiles: props.displayFiles, selectedFiles, setSelectedFiles, statusFilter: [], sortBy: undefined, sortDirection: undefined,
            setSearchQuery: noop, setSearchTagIds: noop, setStatusFilter: noop, setSortBy: noop, setSortDirection: noop,
            setPermTarget: noop, onSearch: noop, onFilterStatus: noop, onSort: noop,
        });
        return { ...permissions, ...selection, selectedFiles };
    }, { initialProps, wrapper });
}
beforeEach(() => {
    jest.clearAllMocks();
    mockUser = { id: '7', role: 'member', tenant_id: 101 };
    jest.mocked(getMyResourcePermissions).mockResolvedValue({ actions: ['download', 'rename'], sources: [], mode: 'INHERIT', roster_complete: true } as never);
    jest.mocked(request.postResponse).mockResolvedValue(response(inspection([11])));
});
afterEach(() => { clients.splice(0).forEach(client => client.clear()); });

it('starts one batch after the page renders and exposes downloads without opening a menu', async () => {
    const pending = deferred<ReturnType<typeof response>>();
    jest.mocked(request.postResponse).mockReturnValue(pending.promise);
    const { result } = mount({ displayFiles: [file('11'), file('12'), file('9', FileType.FOLDER), { ...file('temporary'), isCreating: true }], downloadPages: [['11', '12', '9', 'temporary']] });
    expect(result.current.downloadEntryIds.size).toBe(0);
    act(() => result.current.handleSelectFile('11', true));
    expect(result.current.selectedFiles.has('11')).toBe(true);
    await waitFor(() => expect(request.postResponse).toHaveBeenCalledWith(
        '/api/v1/knowledge/space/3/files/batch/download/inspect', { items: [{ id: 11, type: 'file' }, { id: 12, type: 'file' }, { id: 9, type: 'folder' }] },
    ));
    await act(async () => pending.resolve(response(inspection([11]))));
    await waitFor(() => expect([...result.current.downloadEntryIds]).toEqual(['11']));
    expect(result.current.selectedFiles.has('11')).toBe(true);
    expect(getMyResourcePermissions).not.toHaveBeenCalledWith('knowledge_file', expect.anything());
});

it('checks only the newly appended page and retains earlier download entries', async () => {
    jest.mocked(request.postResponse).mockImplementation(async (_url, body) => response(inspection((body as { items: { id: number }[] }).items.map(item => item.id))));
    const first = file('11'), second = file('12');
    const { result, rerender } = mount({ displayFiles: [first] });
    await waitFor(() => expect(result.current.downloadEntryIds.has('11')).toBe(true));
    rerender({ space, currentFolderId: undefined, displayFiles: [first, second], downloadPages: [['11'], ['12']], downloadEpoch: 1 });
    await waitFor(() => expect([...result.current.downloadEntryIds]).toEqual(['11', '12']));
    expect(jest.mocked(request.postResponse).mock.calls.map(([, body]) => body)).toEqual([
        { items: [{ id: 11, type: 'file' }] }, { items: [{ id: 12, type: 'file' }] },
    ]);
});

it('does not let the menu summary grant a download rejected by the batch', async () => {
    jest.mocked(request.postResponse).mockResolvedValue(response(inspection([])));
    const { result } = mount();
    await act(async () => { await result.current.ensureFilePermissions(file('11')); });
    expect(result.current.renameEntryIds.has('11')).toBe(true);
    expect(result.current.downloadEntryIds.has('11')).toBe(false);
});

it.each(['failed', 'incomplete'])('hides downloads when inspection is %s while keeping menu actions usable', async mode => {
    const error = new Error('Inspection unavailable');
    if (mode === 'failed') jest.mocked(request.postResponse).mockRejectedValue(error);
    else jest.mocked(request.postResponse).mockResolvedValue(response(inspection([11], false)));
    const { result } = mount();
    await waitFor(() => expect(request.postResponse).toHaveBeenCalled());
    await act(async () => { await result.current.ensureFilePermissions(file('11')); });
    expect(result.current.renameEntryIds.has('11')).toBe(true);
    expect(result.current.downloadEntryIds.size).toBe(0);
    if (mode === 'failed') await waitFor(() => expect(showApiError).toHaveBeenCalledWith(error));
});

it.each(['folder', 'listing', 'identity'])('retires late grants through %s A-B-A changes', async kind => {
    const old = deferred<ReturnType<typeof response>>();
    jest.mocked(request.postResponse).mockReturnValueOnce(old.promise).mockResolvedValue(response(inspection([])));
    const initial: Options = { space, currentFolderId: undefined, displayFiles: [file('11')], downloadPages: [['11']], downloadEpoch: 1 };
    const { result, rerender } = mount(initial);
    await waitFor(() => expect(request.postResponse).toHaveBeenCalledTimes(1));
    if (kind === 'identity') mockUser = { ...mockUser, tenant_id: 202 };
    rerender({ ...initial, currentFolderId: kind === 'folder' ? '9' : undefined, downloadEpoch: kind === 'listing' ? 2 : 1 });
    await waitFor(() => expect(request.postResponse).toHaveBeenCalledTimes(2));
    mockUser = { ...mockUser, tenant_id: 101 };
    rerender(initial);
    await waitFor(() => expect(request.postResponse).toHaveBeenCalledTimes(3));
    await act(async () => old.resolve(response(inspection([11]))));
    expect(result.current.downloadEntryIds.size).toBe(0);
});

it('skips invalid IDs and placeholder pages', async () => {
    mount({ displayFiles: [file('0'), { ...file('temporary'), isCreating: true }], downloadPages: [['0', 'temporary']] });
    await act(async () => {});
    expect(request.postResponse).not.toHaveBeenCalled();
});

it('preserves authorized folder ZIP downloads through folder batch inspection', async () => {
    jest.mocked(request.postResponse).mockResolvedValue(response(inspection([], true, [9])));
    const { result } = mount({ displayFiles: [file('9', FileType.FOLDER)], downloadPages: [['9']] });
    await waitFor(() => expect(result.current.downloadEntryIds.has('9')).toBe(true));
    expect(request.postResponse).toHaveBeenCalledWith('/api/v1/knowledge/space/3/files/batch/download/inspect', { items: [{ id: 9, type: 'folder' }] });
});

it('rechecks a reopened file menu and hides actions while the new summary is pending', async () => {
    jest.mocked(getMyResourcePermissions).mockResolvedValue({ actions: ['move', 'delete', 'rename', 'manage_permission'] } as never);
    const { result } = mount();
    await act(async () => { await result.current.ensureFilePermissions(file('11')); });
    expect(result.current.deleteEntryIds.has('11')).toBe(true);
    const pending = deferred<Awaited<ReturnType<typeof getMyResourcePermissions>>>();
    jest.mocked(getMyResourcePermissions).mockReturnValue(pending.promise);
    let reopening!: Promise<void>;
    act(() => { reopening = result.current.ensureFilePermissions(file('11')); });
    await waitFor(() => expect(result.current.pendingFileIds.has('11')).toBe(true));
    expect(result.current.deleteEntryIds.has('11')).toBe(false);
    await act(async () => { pending.resolve({ actions: ['manage_permission'] } as never); await reopening; });
    await waitFor(() => expect(result.current.permissionEntryIds.has('11')).toBe(true));
    expect(result.current.moveEntryIds.size + result.current.deleteEntryIds.size + result.current.renameEntryIds.size).toBe(0);
});

it.each(['folder', 'listing', 'identity'])('retires old file actions when the %s changes with the same row IDs', async kind => {
    jest.mocked(getMyResourcePermissions).mockResolvedValue({ actions: ['move', 'delete', 'create_folder', 'upload_file'] } as never);
    const initial: Options = { space, currentFolderId: undefined, displayFiles: [file('11')], downloadPages: [['11']], downloadEpoch: 1 };
    const { result, rerender } = mount(initial);
    await act(async () => { await result.current.ensureFilePermissions(file('11')); });
    expect(result.current.deleteEntryIds.has('11')).toBe(true);
    const pending = deferred<Awaited<ReturnType<typeof getMyResourcePermissions>>>();
    jest.mocked(getMyResourcePermissions).mockReturnValue(pending.promise);
    if (kind === 'identity') mockUser = { ...mockUser, tenant_id: 202 };
    rerender({ ...initial, currentFolderId: kind === 'folder' ? '9' : undefined, downloadEpoch: kind === 'listing' ? 2 : 1 });
    expect(result.current.moveEntryIds.size + result.current.deleteEntryIds.size).toBe(0);
    expect(result.current.canCreateFolder || result.current.canUploadFile).toBe(false);
    await act(async () => pending.resolve({ actions: ['visible'] } as never));
});

it('ignores a late menu grant after a folder A-B-A navigation', async () => {
    const pending = deferred<Awaited<ReturnType<typeof getMyResourcePermissions>>>();
    jest.mocked(getMyResourcePermissions).mockImplementation((kind) => kind === 'knowledge_file'
        ? pending.promise : Promise.resolve({ actions: [] } as never));
    const initial: Options = { space, currentFolderId: undefined, displayFiles: [file('11')], downloadPages: [['11']], downloadEpoch: 1 };
    const { result, rerender } = mount(initial);
    let opening!: Promise<void>;
    act(() => { opening = result.current.ensureFilePermissions(file('11')); });
    await waitFor(() => expect(result.current.pendingFileIds.has('11')).toBe(true));
    rerender({ ...initial, currentFolderId: '9' });
    rerender(initial);
    await act(async () => { pending.resolve({ actions: ['delete', 'move'] } as never); await opening; });
    expect(result.current.deleteEntryIds.size + result.current.moveEntryIds.size).toBe(0);
});
