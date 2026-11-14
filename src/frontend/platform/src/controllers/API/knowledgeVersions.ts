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

export interface VersionDocumentCandidate {
  document_id: number;
  title: string;
  doc_code?: string | null;
  current_primary_version_no: number;
  primary_uploader_name?: string | null;
  primary_upload_time?: string | null;
  primary_knowledge_file_id?: number | null;
}
export interface SimilarVersionCandidate extends Omit<
  VersionDocumentCandidate,
  "document_id"
> {
  target_document_id: number;
  similarity: number;
}
export interface VersionCandidatePage {
  data: VersionDocumentCandidate[];
  page_size: number;
  has_more: boolean;
  next_cursor: string | null;
}
export interface VersionLinkResult {
  document_id: number;
  new_version_no: number;
}

function requireId(id: number) {
  if (!Number.isSafeInteger(id) || id <= 0)
    throw new RangeError("Resource IDs must be positive safe integers");
}
export async function searchVersionDocuments(
  spaceId: number,
  fileId: number,
  keyword: string,
  sourceOnly: boolean,
  cursor?: string,
  signal?: AbortSignal,
): Promise<VersionCandidatePage> {
  requireId(spaceId);
  requireId(fileId);
  return axios.get(
    `/api/v1/knowledge/space/${spaceId}/document/${sourceOnly ? "version-search-page" : "search-page"}`,
    {
      params: {
        keyword,
        current_file_id: fileId,
        page_size: 40,
        ...(cursor === undefined ? {} : { cursor }),
      },
      signal,
    },
  );
}
export async function getVersionRecommendations(
  fileId: number,
  sourceOnly: boolean,
  signal?: AbortSignal,
): Promise<SimilarVersionCandidate[]> {
  requireId(fileId);
  return axios.get(
    `/api/v1/knowledge/space/file/${fileId}/${sourceOnly ? "version-recommendations" : "similar"}`,
    { signal },
  );
}
export async function linkSpaceFileVersion(
  fileId: number,
  documentId: number,
  signal?: AbortSignal,
): Promise<VersionLinkResult> {
  requireId(fileId);
  requireId(documentId);
  return axios.post(
    "/api/v1/knowledge/space/document/link",
    { knowledge_file_id: fileId, target_document_id: documentId },
    { signal },
  );
}
export async function mergeSpaceFileVersion(
  fileId: number,
  sourceDocumentId: number,
  signal?: AbortSignal,
): Promise<VersionLinkResult> {
  requireId(fileId);
  requireId(sourceDocumentId);
  return axios.post(
    "/api/v1/knowledge/space/version/merge",
    { current_knowledge_file_id: fileId, source_document_id: sourceDocumentId },
    { signal },
  );
}
export async function setSpacePrimaryVersion(
  versionId: number,
  signal?: AbortSignal,
): Promise<{ document_id: number; new_primary_version_no: number }> {
  requireId(versionId);
  return axios.post(
    `/api/v1/knowledge/space/version/${versionId}/set-primary`,
    undefined,
    { signal },
  );
}
export async function deleteSpaceFileVersion(
  versionId: number,
  signal?: AbortSignal,
): Promise<unknown> {
  requireId(versionId);
  return axios.delete(`/api/v1/knowledge/space/version/${versionId}`, {
    signal,
  });
}
export async function dismissSpaceSimilarFile(
  fileId: number,
  signal?: AbortSignal,
): Promise<unknown> {
  requireId(fileId);
  return axios.post(
    `/api/v1/knowledge/space/file/${fileId}/dismiss-similar`,
    undefined,
    { signal },
  );
}

export const knowledgeVersionsApi = {
  getSpaceFileVersions,
  searchVersionDocuments,
  getVersionRecommendations,
  linkSpaceFileVersion,
  mergeSpaceFileVersion,
  setSpacePrimaryVersion,
  deleteSpaceFileVersion,
  dismissSpaceSimilarFile,
};
export type KnowledgeVersionsApi = typeof knowledgeVersionsApi;
