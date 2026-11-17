import { act, renderHook } from '@testing-library/react';
import { useSaveArtifactToKnowledge } from './useSaveArtifactToKnowledge';
import { addFilesApi, searchSpaceChildrenApi, uploadFileToServerApi } from '~/api/knowledge';
import { fetchArtifactBlob } from './artifactUtils';

jest.mock('~/api/knowledge', () => ({ addFilesApi: jest.fn(), searchSpaceChildrenApi: jest.fn(), uploadFileToServerApi: jest.fn(), FileStatus: { UPLOADING: 'uploading', WAITING: 'waiting', PROCESSING: 'processing', REBUILDING: 'rebuilding', FAILED: 'failed' } }));
jest.mock('./artifactUtils', () => ({ fetchArtifactBlob: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks/useEffectiveQuota', () => ({ useRefreshEffectiveQuota: () => jest.fn() }));
jest.mock('~/hooks/usePersonalStorageQuota', () => ({ useStorageQuotaGuard: () => () => false }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));
jest.mock('~/pages/knowledge/hooks/useFileManager', () => ({ dispatchKnowledgeSpaceFilesRefresh: jest.fn() }));

it('registers the final renamed artifact with its own upload reference', async () => {
  jest.mocked(fetchArtifactBlob).mockResolvedValue({ blob: new Blob(['x']), fileName: 'out.md' });
  jest.mocked(searchSpaceChildrenApi).mockResolvedValue({ data: [] } as never);
  jest.mocked(uploadFileToServerApi).mockResolvedValueOnce({ file_path: '/first', preview_upload_ref: 'first-ref', repeat: true } as never).mockResolvedValueOnce({ file_path: '/second', preview_upload_ref: 'second-ref', repeat: false } as never);
  jest.mocked(addFilesApi).mockResolvedValue([{ id: '1', name: 'out(1).md' }] as never);
  const { result } = renderHook(() => useSaveArtifactToKnowledge({ file_name: 'out.md' } as never, 'version'));
  await act(async () => { await result.current.saveTo({ knowledgeSpaceId: '1', folderId: '2' } as never); });
  expect(addFilesApi).toHaveBeenCalledWith('1', { file_path: ['/second'], preview_upload_refs: ['second-ref'], parent_id: 2 });
});
