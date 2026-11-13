import axios from "@/controllers/request";
import type { ProcessingOverrides } from "./knowledgeSpace";
import type { SpaceUploadFile } from "./knowledgeUploads";

export interface UploadContext {
  mode: "previewed" | "direct";
  items: {
    upload_id: string;
    file_path: string;
    overrides: ProcessingOverrides;
    preview_id?: string;
    expected_revision?: number;
  }[];
}
export interface UploadPreview {
  preview_id: string;
  revision: number;
  status: "processing" | "completed" | "error";
  data?: {
    code?: number;
    file_url: string;
    parse_type: string;
    partitions: Record<string, { text: string; type: string; part_id: string }>;
    chunks: {
      text: string;
      metadata: { chunk_index: number; bbox?: string; [key: string]: unknown };
    }[];
  };
}
const path = (spaceId: number, uploadId?: string) => {
  if (!Number.isSafeInteger(spaceId) || spaceId <= 0)
    throw new RangeError("Invalid space ID");
  if (uploadId !== undefined && !/^[0-9a-f]{32}$/.test(uploadId))
    throw new RangeError("Invalid upload ID");
  return `/api/v1/knowledge/space/${spaceId}/uploads${uploadId ? `/${uploadId}` : ""}`;
};
export const knowledgeUploadPreviewApi = {
  stageFile: (
    spaceId: number,
    parentId: number | null,
    file: File,
    signal?: AbortSignal,
  ): Promise<SpaceUploadFile> => {
    const body = new FormData();
    body.append("file", file);
    return axios.post(path(spaceId), body, {
      params: parentId === null ? {} : { parent_id: parentId },
      signal,
    });
  },
  start: (
    spaceId: number,
    uploadId: string,
    overrides: ProcessingOverrides,
    signal?: AbortSignal,
  ): Promise<{ preview_id: string }> =>
    axios.post(
      `${path(spaceId, uploadId)}/previews`,
      { overrides },
      { signal },
    ),
  read: (
    spaceId: number,
    uploadId: string,
    previewId: string,
    signal?: AbortSignal,
  ): Promise<UploadPreview> =>
    axios.get(`${path(spaceId, uploadId)}/previews/${previewId}`, { signal }),
  edit: (
    spaceId: number,
    uploadId: string,
    previewId: string,
    index: number,
    revision: number,
    text: string,
    bbox: string,
    signal?: AbortSignal,
  ): Promise<UploadPreview> =>
    axios.put(
      `${path(spaceId, uploadId)}/previews/${previewId}/chunks/${index}`,
      { text, bbox, expected_revision: revision },
      { signal },
    ),
  delete: (
    spaceId: number,
    uploadId: string,
    previewId: string,
    index: number,
    revision: number,
    signal?: AbortSignal,
  ): Promise<UploadPreview> =>
    axios.delete(
      `${path(spaceId, uploadId)}/previews/${previewId}/chunks/${index}`,
      { params: { expected_revision: revision }, signal },
    ),
};
