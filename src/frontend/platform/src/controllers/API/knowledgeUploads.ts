import axios from "@/controllers/request";
import type {
  KnowledgeSpaceChild,
  ProcessingOverrides,
  ProcessingSettingsRead,
} from "./knowledgeSpace";

export interface SpaceUploadFile {
  flowId?: string | null;
  file_path: string;
  relative_path?: string | null;
  file_name?: string | null;
  repeat: boolean;
  repeat_file_name?: string | null;
  repeat_update_time?: string | null;
  cover_filepath?: string | null;
}

export interface SpaceFilesCreate {
  file_path: string[];
  parent_id?: number | null;
  overrides?: ProcessingOverrides | null;
}

function requireId(value: number): void {
  if (!Number.isSafeInteger(value) || value <= 0)
    throw new RangeError("Resource IDs must be positive safe integers");
}

export async function uploadSpaceFile(
  spaceId: number,
  file: File,
  signal?: AbortSignal,
): Promise<SpaceUploadFile> {
  requireId(spaceId);
  const body = new FormData();
  body.append("file", file);
  return axios.post(`/api/v1/knowledge/upload/${spaceId}`, body, { signal });
}

export async function registerSpaceFiles(
  spaceId: number,
  body: SpaceFilesCreate,
  signal?: AbortSignal,
): Promise<KnowledgeSpaceChild[]> {
  requireId(spaceId);
  if (body.parent_id != null) requireId(body.parent_id);
  return axios.post(
    `/api/v1/knowledge/space/${spaceId}/files`,
    {
      file_path: body.file_path.slice(),
      ...(body.parent_id === undefined ? {} : { parent_id: body.parent_id }),
      ...(body.overrides === undefined ? {} : { overrides: body.overrides }),
    },
    { signal },
  );
}

export async function getUploadSettings(
  spaceId: number,
  parentId?: number | null,
  signal?: AbortSignal,
): Promise<ProcessingSettingsRead> {
  requireId(spaceId);
  if (parentId != null) requireId(parentId);
  return axios.get(`/api/v1/knowledge/space/${spaceId}/files/upload-settings`, {
    params: parentId == null ? {} : { parent_id: parentId },
    signal,
  });
}

export const knowledgeUploadsApi = {
  uploadSpaceFile,
  registerSpaceFiles,
  getUploadSettings,
};
export type KnowledgeUploadsApi = typeof knowledgeUploadsApi;
