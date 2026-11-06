import axios from "@/controllers/request";

export interface SpaceVersionEntry {
  version_id: number;
  version_no: number;
  is_primary: boolean;
  knowledge_file_id: number;
  original_file_name: string;
  file_code: string | null;
  uploader_name: string | null;
  uploader_id: number | null;
  upload_time: string | null;
  status: number | null;
}

export interface SpaceVersionHistory {
  document_id: number;
  knowledge_id: number;
  title: string;
  doc_code: string | null;
  current_primary_version_no: number | null;
  versions: SpaceVersionEntry[];
}

export async function getSpaceFileVersions(
  fileId: number,
  signal?: AbortSignal,
): Promise<SpaceVersionHistory> {
  if (!Number.isSafeInteger(fileId) || fileId <= 0) {
    throw new RangeError("Resource IDs must be positive safe integers");
  }
  return axios.get(`/api/v1/knowledge/space/file/${fileId}/versions`, {
    signal,
  });
}

export const knowledgeVersionsApi = { getSpaceFileVersions };
export type KnowledgeVersionsApi = typeof knowledgeVersionsApi;
