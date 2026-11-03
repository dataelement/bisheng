import { normalizeApiError } from '@bisheng/api-client';
import type { UploadFileResponse } from './knowledge';
import request from './request';

interface UploadResponse {
  status_code?: number;
  status_message?: string;
  data?: UploadFileResponse;
}

/** Pin the upload to a fresh server-confirmed view of the target space. */
export async function uploadFileToServerApi(
  spaceId: string,
  file: File,
  filename?: string,
): Promise<UploadFileResponse> {
  const space = await request.getResponse<{ headers: Record<string, unknown> }>(
    `/api/v1/knowledge/space/${spaceId}/info`,
  );
  const tenant = space.headers['x-management-tenant'];
  // Older backends do not require or return the management-tenant header.
  const headers = tenant == null ? undefined : { 'X-Management-Tenant': String(tenant) };
  const formData = new FormData();
  // Directory pickers may put the relative path into file.name; keep the caller's basename.
  formData.append('file', file, filename ?? file.name);
  const response = await request.postMultiPart(
    `/api/v1/knowledge/upload/${spaceId}`,
    formData,
    { headers },
  ) as UploadResponse;
  if (response?.status_code !== undefined && response.status_code !== 200) {
    throw normalizeApiError(response, { message: response.status_message || 'Upload failed' });
  }
  if (!response?.data?.file_path) throw new Error('Upload response is missing the file path');
  return response.data;
}
