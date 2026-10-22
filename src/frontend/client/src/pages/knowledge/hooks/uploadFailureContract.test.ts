import { normalizeApiError } from '@bisheng/api-client';
import { uploadFileToServerApi } from '~/api/knowledge';
import { uploadFilesSequential } from './useFileUpload';
jest.mock('~/api/knowledge', () => ({ uploadFileToServerApi: jest.fn(), FileStatus: { UPLOADING: 'UPLOADING', WAITING: 'WAITING', PROCESSING: 'PROCESSING', REBUILDING: 'REBUILDING' } }));
jest.mock('./useFileManager', () => ({ dispatchKnowledgeSpaceFilesRefresh: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: jest.fn() }));
jest.mock('~/hooks/useEffectiveQuota', () => ({ useRefreshEffectiveQuota: jest.fn() }));
jest.mock('~/hooks/usePersonalStorageQuota', () => ({ useStorageQuotaGuard: jest.fn() }));
jest.mock('~/Providers', () => ({ useToastContext: jest.fn() }));
jest.mock('i18next', () => ({ __esModule: true, default: {
  exists: (key: string) => key === 'api_errors.19403',
  t: (_key: string, data: { used_gb?: number; quota_gb?: number }) => `${data.used_gb}/${data.quota_gb} GB`,
} }));
it('stops a failed quota batch and retains interpolation values from the canonical error', async () => {
  const error = normalizeApiError({ status_code: 19403, data: { used_gb: 10, quota_gb: 10 } }, { message: 'storage exhausted' });
  (uploadFileToServerApi as jest.Mock).mockRejectedValue(error);
  const success = jest.fn();
  const files = [new File(['a'], 'one.txt'), new File(['b'], 'two.txt')];
  const result = await uploadFilesSequential('1', files, success);
  expect(uploadFileToServerApi).toHaveBeenCalledTimes(1);
  expect(success).not.toHaveBeenCalled();
  expect(result.earlyStop).toEqual({ reason: '10/10 GB', statusCode: 19403, skippedCount: 1 });
});
