import request, { prepareBrowserHeaders } from './request';

type Envelope<T> = { status_code: number; data: T };
type CapabilityResponse = { provider_key: string; capability_revision: number; generation?: unknown; capabilities: Record<string, unknown> };
const spacePath = (spaceId: string) => `/api/v1/knowledge/space/${encodeURIComponent(spaceId)}`;
const positiveId = (id: unknown): id is number => typeof id === 'number' && Number.isSafeInteger(id) && id > 0;

export async function readFileCapabilities(spaceId: string, signal?: AbortSignal) {
  const response = await request.getResponse<{ headers: Record<string, string>; data: Envelope<CapabilityResponse> }>(`${spacePath(spaceId)}/capabilities`, { signal });
  const raw = response.data.data;
  if (response.data.status_code !== 200 || !raw || !positiveId(raw.capability_revision) || !raw.capabilities ||
    (raw.provider_key !== 'native' && raw.provider_key !== 'weknora')) throw new Error('Unverified file capabilities');
  const native = raw.provider_key === 'native';
  const tenant = response.headers['x-management-tenant'];
  return {
    native, tenant, revision: raw.capability_revision,
    generation: positiveId(raw.generation) ? raw.generation : undefined,
    tagReadable: !native && [raw.capabilities.tag_vocabulary, raw.capabilities.tag_selection]
      .every(state => state === 'supported' || state === 'conditional'),
    tagEditable: !native && (raw.capabilities.tag_edit === 'supported' || raw.capabilities.tag_edit === 'conditional'),
    providerUpload: !native && raw.capabilities.upload === 'supported' && /^[1-9]\d*$/.test(tenant),
    providerFolderUpload: !native && raw.capabilities.folder_upload === 'supported' && /^[1-9]\d*$/.test(tenant),
    preview: raw.capabilities.preview === 'supported' || (!native && raw.capabilities.preview === 'conditional' && raw.capabilities.preview_representation === 'text_excerpt'),
  };
}

export type ProviderFolderPrepareResult = {
  root_name: string;
  folders: { relative_dir: string; folder_id: number }[];
};

/** Relative directory of a folder-upload file path (drop-point relative). */
export function parentDirOfRelativePath(relativePath: string): string {
  const parts = relativePath.replace(/\\/g, '/').split('/').filter(Boolean);
  return parts.slice(0, -1).join('/');
}

export async function prepareProviderFolderUpload(
  spaceId: string,
  data: { parent_id?: number | null; paths: string[] },
  tenant: string,
): Promise<ProviderFolderPrepareResult> {
  const endpoint = `${spacePath(spaceId)}/provider-folder-uploads/prepare`;
  const headers = await prepareBrowserHeaders('POST', endpoint);
  if (headers['X-Management-Tenant'] !== tenant) throw new Error('Upload scope changed');
  const response = await request.postResponse<{ data: Envelope<ProviderFolderPrepareResult> }>(endpoint, data, {
    managementContext: 'independent',
    headers: { 'X-Management-Tenant': tenant },
  });
  const envelope = response.data;
  const raw = envelope?.data;
  if (
    envelope?.status_code !== 200 ||
    !raw ||
    typeof raw.root_name !== 'string' ||
    !raw.root_name ||
    !Array.isArray(raw.folders) ||
    raw.folders.some(
      (row) =>
        typeof row?.relative_dir !== 'string' ||
        !row.relative_dir ||
        !positiveId(row.folder_id),
    )
  ) {
    throw new Error('Unverified folder prepare response');
  }
  return { root_name: raw.root_name, folders: raw.folders.map((row) => ({ relative_dir: row.relative_dir, folder_id: row.folder_id })) };
}

export type UploadReceipt = { operation_id: string; file_id: number; version_id: number };
export type UploadOutcome = { state: 'unknown' | 'accepted' | 'reupload_required' | 'conflict'; receipt?: UploadReceipt };
export type UploadTarget = { spaceId: string; parentId?: string; key: string; tenant: string };
function outcome(envelope: Envelope<Partial<UploadReceipt> & { state?: string }>): UploadOutcome {
  const raw = envelope?.data;
  if (envelope?.status_code !== 200 || typeof raw?.operation_id !== 'string' || !raw.operation_id.trim() || !positiveId(raw.file_id) || !positiveId(raw.version_id)) return { state: 'unknown' };
  const receipt = { operation_id: raw.operation_id, file_id: raw.file_id, version_id: raw.version_id };
  switch (raw.state) {
    case 'accepted': case 'reupload_required': case 'conflict': return { state: raw.state, receipt };
    default: return { state: 'unknown', receipt };
  }
}
const itemPath = (t: UploadTarget) => `${spacePath(t.spaceId)}/provider-uploads/${encodeURIComponent(t.key)}`;
async function verifyScope(method: string, target: UploadTarget) {
  const headers = await prepareBrowserHeaders(method, itemPath(target));
  if (headers['X-Management-Tenant'] !== target.tenant) throw new Error('Upload scope changed');
}
export async function sendProviderFile(target: UploadTarget, file: File, checksum: string) {
  await verifyScope('POST', target);
  return outcome(await request.post(itemPath(target), file, {
    managementContext: 'independent',
    headers: { 'Content-Type': 'application/octet-stream', 'X-Management-Tenant': target.tenant },
    params: { file_name: file.name, byte_count: file.size, sha256: checksum, ...(target.parentId ? { parent_id: Number(target.parentId) } : {}) },
  }));
}
export async function checkProviderFile(target: UploadTarget) {
  await verifyScope('GET', target);
  return outcome(await request.get(itemPath(target), {
    managementContext: 'independent',
    headers: { 'X-Management-Tenant': target.tenant },
    params: target.parentId ? { parent_id: Number(target.parentId) } : {},
  }));
}
