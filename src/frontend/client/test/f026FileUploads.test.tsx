import { webcrypto } from 'node:crypto';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { useKnowledgeUploads } from '~/pages/knowledge/SpaceDetail/useKnowledgeUploads';
import type { KnowledgeSpace } from '~/api/knowledge';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useProviderFileUploads } from '~/pages/knowledge/hooks/useProviderFileUploads';
import { ProviderUploadResults } from '~/pages/knowledge/SpaceDetail/ProviderUploadResults';

const http = vi.hoisted(() => ({ getResponse: vi.fn(), get: vi.fn(), post: vi.fn() }));
const scope = vi.hoisted(() => vi.fn());
vi.mock('~/api/request', () => ({ default: http, prepareBrowserHeaders: scope, showApiError: vi.fn() }));
vi.mock('~/pages/knowledge/hooks/useFileManager', () => ({ dispatchKnowledgeSpaceFilesRefresh: vi.fn() }));
vi.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: { id: '2', role: 'member', tenant_id: 7 } }) }));
const native = vi.fn(), refresh = vi.fn();
const envelope = (data: unknown) => ({ status_code: 200, data });
const receipt = (state: string, n: number) => envelope({ state, operation_id: `op-${n}`, file_id: n, version_id: n + 10 });
let provider: string, upload: unknown;
const path = '/api/v1/knowledge/space/9';
function Form({ rights = ['visible', 'upload_file'], folder = '3' }: { rights?: string[]; folder?: string }) {
  const flow = useProviderFileUploads('9', folder, rights.includes('upload_file'), native, refresh);
  const pickerActions = useKnowledgeUploads({
    localize: k => k, setContextMenuOpen: vi.fn(), setContextMenuPosition: vi.fn(), queryClient: useQueryClient(),
    canUploadFile: flow.canUploadFile, canUploadNativeExtras: flow.canUploadNativeExtras, canUseContextMenuActions: flow.canUploadFile,
    showToast: vi.fn(), confirm: vi.fn(), refreshQuota: vi.fn(), isStorageBlocked: () => false,
    uploadSizeLimits: { defaultMaxMB: 5, mediaMaxMB: 5 }, maxFileSizeMB: 5, enableEtl4lm: false, allowedExtensions: ['txt'],
    space: { id: '9' } as KnowledgeSpace, onUploadFile: flow.uploadFiles, onUploadFolder: vi.fn(), onDeleteFile: refresh,
    currentFolderId: folder, onDragStateChange: vi.fn(),
  });
  return <><input ref={pickerActions.fileInputRef} aria-label="files" type="file" multiple disabled={!flow.canUploadFile} onChange={pickerActions.handleFileChange} />
    <output>{String(flow.canUploadNativeExtras)}</output><ProviderUploadResults items={flow.items} onCheck={flow.check} onRetry={flow.retry} /></>;
}
function open(rights?: string[]) { return render(<QueryClientProvider client={new QueryClient()}><Form rights={rights} /></QueryClientProvider>); }
const picker = () => screen.getByLabelText<HTMLInputElement>('files');
const pick = async () => {
  await waitFor(() => expect(picker().disabled).toBe(false));
  const files = ['a.txt', 'b.txt'].map(name => Object.assign(new File(['hi'], name), { arrayBuffer: async () => Buffer.alloc(2).fill('hi').buffer }));
  fireEvent.change(picker(), { target: { files } });
  return files;
};
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal('crypto', webcrypto); provider = 'weknora'; upload = 'supported';
  scope.mockResolvedValue({ 'X-Management-Tenant': '7' });
  http.getResponse.mockImplementation(async (url: string) => {
    if (url !== `${path}/capabilities`) throw new Error('Unexpected capability request');
    return { headers: { 'x-management-tenant': '7' }, data: envelope({ provider_key: provider, capability_revision: 1, capabilities: { upload, preview: 'conditional', preview_representation: 'text_excerpt' } }) };
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('posts each file once without edit; only retries the confirmed missing item with its original bytes and key', async () => {
  http.post.mockResolvedValueOnce(receipt('accepted', 1)).mockResolvedValueOnce(receipt('reupload_required', 2)).mockResolvedValueOnce(receipt('accepted', 2));
  open(); const files = await pick();
  const retry = await screen.findByRole('button', { name: 'com_knowledge.retry' });
  expect(http.post).toHaveBeenCalledTimes(2); expect(native).not.toHaveBeenCalled();
  const [first, second] = http.post.mock.calls;
  expect(first[0]).toMatch(/^\/api\/v1\/knowledge\/space\/9\/provider-uploads\/[\w-]+$/); expect(second[0]).not.toBe(first[0]);
  expect(first[1]).toBe(files[0]); expect(second[1]).toBe(files[1]);
  expect(first[2]).toMatchObject({ params: { file_name: 'a.txt', byte_count: 2, sha256: '8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4', parent_id: 3 }, headers: { 'Content-Type': 'application/octet-stream', 'X-Management-Tenant': '7' } });
  expect(screen.getByText('com_knowledge.provider_upload_received')).toBeTruthy();
  fireEvent.click(retry); await waitFor(() => expect(http.post.mock.calls[2]).toEqual(second));
  await waitFor(() => expect(screen.getAllByText('com_knowledge.provider_upload_received')).toHaveLength(2));
});
it.each(['unknown', 'lost', 'invalid', 'future'])('never replays uncertain item (%s); GET by original key only', async state => {
  http.post.mockResolvedValueOnce(receipt('accepted', 1));
  if (state === 'lost') http.post.mockRejectedValueOnce(new Error('Disconnected'));
  else if (state === 'invalid') http.post.mockResolvedValueOnce(envelope({ state: 'accepted' }));
  else http.post.mockResolvedValueOnce(receipt(state, 2));
  http.get.mockResolvedValueOnce(envelope({ state: 'not_found' })).mockResolvedValueOnce(receipt('accepted', 2));
  open(); await pick();
  const row = (await screen.findByText('com_knowledge.provider_upload_unknown')).closest('li')!;
  expect(within(row).queryByText('com_knowledge.retry')).toBeNull();
  const check = () => within(row).getByRole('button', { name: 'com_knowledge.provider_upload_check' });
  fireEvent.click(check()); await waitFor(() => expect(http.get).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(check().hasAttribute('disabled')).toBe(false)); fireEvent.click(check());
  await waitFor(() => expect(screen.getAllByText('com_knowledge.provider_upload_received')).toHaveLength(2));
  expect(http.get.mock.calls.map(call => call[0])).toEqual(Array(2).fill(http.post.mock.calls[1][0])); expect(http.post).toHaveBeenCalledTimes(2);
});
it.each([undefined, 'unverified', 'unsupported', true])('blocks external bytes when upload is %s, regardless of edit', async flag => {
  upload = flag; open(['visible', 'edit', 'upload_file']); await waitFor(() => expect(http.getResponse).toHaveBeenCalled());
  expect(picker().disabled).toBe(true); expect(screen.getByText('false')).toBeTruthy(); expect(native).not.toHaveBeenCalled();
});
it('does not send bytes after the active tenant changes', async () => {
  scope.mockResolvedValue({ 'X-Management-Tenant': '8' }); open(); await pick();
  await waitFor(() => expect(scope).toHaveBeenCalled()); expect(http.post).not.toHaveBeenCalled(); expect(native).not.toHaveBeenCalled();
});
it('rejects a different file or version receipt even on a matching request key', async () => {
  http.post.mockResolvedValueOnce(receipt('unknown', 1)).mockResolvedValueOnce(receipt('accepted', 2));
  http.get.mockResolvedValueOnce(receipt('accepted', 3)); open(); await pick();
  fireEvent.click(await screen.findByRole('button', { name: 'com_knowledge.provider_upload_check' }));
  await screen.findByText('com_knowledge.provider_upload_conflict'); expect(http.post).toHaveBeenCalledTimes(2);
});
it('never grants upload from edit alone', async () => {
  open(['visible', 'edit']); await waitFor(() => expect(http.getResponse).toHaveBeenCalled()); expect(picker().disabled).toBe(true);
});
it('preserves both files and ordinary extras on confirmed Native', async () => {
  provider = 'native'; upload = undefined; open(); const files = await pick(); expect(native).toHaveBeenCalledWith(files); expect(http.post).not.toHaveBeenCalled(); expect(screen.getByText('true')).toBeTruthy();
});
