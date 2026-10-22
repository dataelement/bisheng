import { act, renderHook } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import { addFilesApi, uploadFileToServerApi, uploadFolderApi, listKnowledgeFolders, deleteFileApi, retryDuplicateFilesApi } from '~/api/knowledge';
import { showApiError } from '~/api/request';
import { uploadFilesSequential, useFileUpload, buildUploadFailureMessage } from './useFileUpload';
const mockToast = jest.fn();
const mockSetFiles = jest.fn();
const mockClearPending = jest.fn();
const mockLoadFiles = jest.fn(async () => undefined);
const mockRefresh = jest.fn(async () => undefined);
const localize = (key: string, options?: Record<string, unknown>) => `${key}${options ? ':' + JSON.stringify(options) : ''}`;
jest.mock('~/api/knowledge', () => ({ uploadFileToServerApi: jest.fn(), addFilesApi: jest.fn(), uploadFolderApi: jest.fn(), listKnowledgeFolders: jest.fn(), deleteFileApi: jest.fn(), retryDuplicateFilesApi: jest.fn(), FileStatus: { UPLOADING: 'uploading', WAITING: 'waiting', PROCESSING: 'processing', REBUILDING: 'rebuilding', FAILED: 'failed' }, FileType: { FOLDER: 'folder' } }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));
jest.mock('./useFileManager', () => ({ dispatchKnowledgeSpaceFilesRefresh: jest.fn() }));
jest.mock('../knowledgeUtils', () => ({ getFileTypeFromName: () => 'txt', isKnowledgeItemPending: () => false, getRootFolderName: (path: string) => path.split('/')[0], isHiddenName: () => false, MAX_FOLDER_DEPTH: 10, MAX_FOLDER_UPLOAD_COUNT: 1000, filterFolderUploadFiles: (files: File[]) => ({ valid: files, oversizeCount: 0, unsupportedCount: 0 }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => localize }));
jest.mock('~/hooks/useEffectiveQuota', () => ({ useRefreshEffectiveQuota: () => mockRefresh }));
jest.mock('~/hooks/usePersonalStorageQuota', () => ({ useStorageQuotaGuard: () => () => false }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock('i18next', () => ({ __esModule: true, default: { exists: (key: string) => key === 'api_errors.19403', t: (_key: string, data: { used_gb?: number; quota_gb?: number }) => `${data.used_gb}/${data.quota_gb} GB` } }));
const files = [new File(['a'], 'one.txt'), new File(['b'], 'two.txt')];
const folderFiles = files.map(file => { Object.defineProperty(file, 'webkitRelativePath', { value: `Docs/${file.name}`, configurable: true }); return file; });
const makeError = (kind: string) => {
  const cause = kind === 'canceled' ? { code: 'ERR_CANCELED' } : kind === 'network' ? { code: 'ERR_NETWORK' } : kind === 'timeout' ? { code: 'ECONNABORTED' } : kind === 'invalid' ? new Error('invalid response') : kind === 'http' ? { response: { status: 503, data: { status_code: 500 } } } : { status_code: 19403, data: { used_gb: 9, quota_gb: 9 } };
  const error = normalizeApiError(cause, { message: 'Upload unavailable' });
  if (kind === 'global') error.presentation = 'global';
  return error;
};
const mount = (knownFiles: Parameters<typeof useFileUpload>[0]['files'] = []) => renderHook(() => useFileUpload({ activeSpace: { id: '1' } as Parameters<typeof useFileUpload>[0]['activeSpace'], currentFolderId: undefined, currentPath: [], files: knownFiles, setFiles: mockSetFiles, setTotal: jest.fn(), loadFiles: mockLoadFiles, currentPage: 1, markPendingDeletion: jest.fn(), clearPendingDeletion: mockClearPending }));
beforeEach(() => { jest.clearAllMocks(); (uploadFileToServerApi as jest.Mock).mockReset().mockResolvedValue({ file_path: '/upload/one.txt' }); (addFilesApi as jest.Mock).mockReset().mockResolvedValue([]); (uploadFolderApi as jest.Mock).mockReset().mockResolvedValue([]); (listKnowledgeFolders as jest.Mock).mockReset().mockResolvedValue({ items: [] }); });
it.each(['global', 'canceled'])('immediately rejects the same %s upload error without continuing the batch', async kind => {
  const error = makeError(kind);
  (uploadFileToServerApi as jest.Mock).mockRejectedValueOnce(error);
  await expect(uploadFilesSequential('1', files, jest.fn())).rejects.toBe(error);
  expect(uploadFileToServerApi).toHaveBeenCalledTimes(1);
});
it('keeps full ordinary error evidence and the named quota summary', async () => {
  const error = makeError('business');
  (uploadFileToServerApi as jest.Mock).mockRejectedValueOnce(error);
  const result = await uploadFilesSequential('1', files, jest.fn());
  expect(result.failures[0].error).toBe(error);
  expect(result.earlyStop).toEqual({ reason: '9/9 GB', statusCode: 19403, skippedCount: 1 });
  expect(buildUploadFailureMessage(result.failures, result.earlyStop, localize)).toContain('"0":2');
});
describe.each(['file', 'folder'])('%s upload UI cleanup', surface => {
  it.each(['global', 'canceled'])('consumes %s errors, clears its placeholder, and allows the next batch', async kind => {
    const error = makeError(kind);
    (uploadFileToServerApi as jest.Mock).mockResolvedValueOnce({ file_path: '/partial' }).mockRejectedValueOnce(error);
    const { result } = mount();
    const run = () => surface === 'file' ? result.current.handleUploadFile(files) : result.current.handleUploadFolder(folderFiles, { allowedExtensions: ['txt'], maxSizeMB: 10 });
    await act(async () => { await run(); });
    expect(result.current.uploadingFiles).toEqual([]);
    expect(result.current.uploadingFolder).toBeNull();
    expect(mockRefresh).toHaveBeenCalledTimes(1);
    expect(showApiError).toHaveBeenCalledWith(error);
    expect(showApiError).toHaveBeenCalledTimes(1);
    expect((showApiError as jest.Mock).mock.calls[0]?.[0]).toBe(error);
    expect(mockToast).not.toHaveBeenCalled();
    expect(addFilesApi).not.toHaveBeenCalled();
    expect(uploadFolderApi).not.toHaveBeenCalled();
    await act(async () => { await run(); });
    expect(surface === 'file' ? addFilesApi : uploadFolderApi).toHaveBeenCalledTimes(1);
  });
});
it.each(['business', 'global', 'canceled', 'invalid', 'local'])('does not retry %s registration failures or report global/cancel as an ordinary failure', async kind => {
  const error = kind === 'local' ? new Error('local register failed') : makeError(kind);
  (addFilesApi as jest.Mock).mockRejectedValue(error);
  const { result } = mount();
  await act(async () => { await result.current.handleUploadFile(files); });
  expect(addFilesApi).toHaveBeenCalledTimes(1);
  expect(result.current.uploadingFiles).toEqual([]);
  if (kind === 'local') expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ message: 'com_knowledge.file_register_failed' }));
  else { expect(showApiError).toHaveBeenCalledWith(error); expect(mockToast).not.toHaveBeenCalled(); }
});
it.each(['network', 'timeout', 'http'])('retains a single %s registration retry without uploading the body again', async kind => {
  (addFilesApi as jest.Mock).mockRejectedValueOnce(makeError(kind)).mockResolvedValueOnce([]);
  const { result } = mount();
  await act(async () => { await result.current.handleUploadFile([files[0]]); });
  expect(addFilesApi).toHaveBeenCalledTimes(2);
  expect(uploadFileToServerApi).toHaveBeenCalledTimes(1);
  expect(result.current.uploadingFiles).toEqual([]);
  expect(mockToast).not.toHaveBeenCalled();
});
it('stops a folder batch when its duplicate-name precheck is globally rejected', async () => {
  const error = makeError('global');
  (listKnowledgeFolders as jest.Mock).mockRejectedValueOnce(error);
  const { result } = mount();
  await act(async () => { await result.current.handleUploadFolder(folderFiles, { allowedExtensions: ['txt'], maxSizeMB: 10 }); });
  expect(uploadFileToServerApi).not.toHaveBeenCalled();
  expect(showApiError).toHaveBeenCalledWith(error);
    expect(showApiError).toHaveBeenCalledTimes(1);
    expect((showApiError as jest.Mock).mock.calls[0]?.[0]).toBe(error);
  expect(mockToast).not.toHaveBeenCalled();
  expect(result.current.uploadingFolder).toBeNull();
});

it.each(['global', 'canceled'])('preserves deletion rollback without an ordinary toast for %s errors', async kind => {
  const error = makeError(kind);
  (deleteFileApi as jest.Mock).mockRejectedValueOnce(error);
  const existing = { id: 'kept', type: 'txt' } as Parameters<typeof useFileUpload>[0]['files'][number];
  const { result } = mount([existing]);
  await act(async () => { await result.current.handleDeleteFile('kept'); });
  expect(mockSetFiles.mock.calls[0][0]([existing])).toEqual([]);
  expect(mockClearPending).toHaveBeenCalledWith(['kept']);
  expect(mockLoadFiles).toHaveBeenCalledWith(1);
  expect(showApiError).toHaveBeenCalledTimes(1);
  expect((showApiError as jest.Mock).mock.calls[0]?.[0]).toBe(error);
  expect(mockToast).not.toHaveBeenCalled();
});
it.each(['global', 'canceled'])('does not duplicate the %s notice when duplicate-file overwrite fails', async kind => {
  (addFilesApi as jest.Mock).mockResolvedValueOnce([{ id: 'duplicate', name: 'one.txt', status: 'failed', oldFileLevelPath: '', _raw: { id: 1 } }]);
  const error = makeError(kind);
  (retryDuplicateFilesApi as jest.Mock).mockRejectedValueOnce(error);
  const { result } = mount();
  await act(async () => { await result.current.handleUploadFile([files[0]]); });
  expect(result.current.duplicateFiles).toHaveLength(1);
  await act(async () => { await result.current.handleDuplicateOverwrite(); });
  expect(showApiError).toHaveBeenCalledTimes(1);
  expect((showApiError as jest.Mock).mock.calls[0]?.[0]).toBe(error);
  expect(mockToast).not.toHaveBeenCalled();
  expect(result.current.duplicateFiles).toEqual([]);
});
it('does not exceed the existing one-retry registration budget', async () => {
  const error = makeError('network');
  (addFilesApi as jest.Mock).mockRejectedValue(error);
  const { result } = mount();
  await act(async () => { await result.current.handleUploadFile([files[0]]); });
  expect(addFilesApi).toHaveBeenCalledTimes(2);
  expect(uploadFileToServerApi).toHaveBeenCalledTimes(1);
  expect(showApiError).toHaveBeenCalledTimes(1);
  expect((showApiError as jest.Mock).mock.calls[0]?.[0]).toBe(error);
  expect(result.current.uploadingFiles).toEqual([]);
});
it('retains ordinary per-file evidence and continues to the next body upload', async () => {
  const error = normalizeApiError({ status_code: 10953, data: { exception: 'parse unavailable' } }, { message: 'parse unavailable' });
  (uploadFileToServerApi as jest.Mock).mockRejectedValueOnce(error);
  const uploaded: string[] = [];
  const result = await uploadFilesSequential('1', files, (_response, file) => uploaded.push(file.name));
  expect(result.failures[0].error).toBe(error);
  expect(result.failures[0].reason).toBe('parse unavailable');
  expect(uploaded).toEqual(['two.txt']);
});
