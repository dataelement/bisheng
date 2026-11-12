import axios from "@/controllers/request";
import type { PageData } from "./knowledgeSpace";
export interface SpaceChunk {
  text: string;
  metadata: { document_id: number; chunk_index: number; bbox?: string | null };
}
export interface FileMetadata {
  user_metadata?: Record<
    string,
    { field_value: unknown; field_type?: string }
  > | null;
}
export function readVersionChunks(
  spaceId: number,
  fileId: number,
  page: number,
): Promise<PageData<SpaceChunk>> {
  return axios.get("/api/v1/knowledge/chunk", {
    params: { knowledge_id: spaceId, file_ids: [fileId], page, limit: 10 },
    paramsSerializer: { indexes: null },
  });
}
export function updateVersionChunk(
  spaceId: number,
  fileId: number,
  chunk: SpaceChunk,
  text: string,
): Promise<unknown> {
  return axios.put("/api/v1/knowledge/chunk", {
    knowledge_id: spaceId,
    file_id: fileId,
    chunk_index: chunk.metadata.chunk_index,
    text,
    bbox: chunk.metadata.bbox ?? "",
  });
}
export function deleteVersionChunk(
  spaceId: number,
  fileId: number,
  chunk: SpaceChunk,
): Promise<unknown> {
  return axios.delete("/api/v1/knowledge/chunk", {
    data: {
      knowledge_id: spaceId,
      file_id: fileId,
      chunk_index: chunk.metadata.chunk_index,
    },
  });
}
export function readFileMetadata(fileId: number): Promise<FileMetadata> {
  return axios.get(`/api/v1/knowledge/file/info/${fileId}`);
}
export function updateFileMetadata(
  fileId: number,
  values: Record<string, string>,
): Promise<unknown> {
  return axios.put("/api/v1/knowledge/file/user_metadata", {
    knowledge_file_id: fileId,
    user_metadata_list: Object.entries(values).map(
      ([field_name, field_value]) => ({ field_name, field_value }),
    ),
  });
}
