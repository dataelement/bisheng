import axios from "@/controllers/request";
import type {
  KnowledgeChildrenQuery,
  KnowledgeSpaceChild,
} from "./knowledgeSpace";

export interface SpaceFolderParent {
  id: number;
  file_name: string | number;
}
export interface SpaceFileUrls {
  original_url: string;
  preview_url: string;
}
export interface SpaceFilePreview extends SpaceFileUrls {
  file_source: string | null;
  source_url: string;
  final_url: string;
  web_title: string;
  media_kind: string;
  html_preview_url: string;
}
export interface SpaceSearchQuery {
  keyword?: string;
  parent_id?: number | null;
  tag_ids?: number[];
  file_status?: number[];
  page: number;
  page_size: number;
  order_field?: KnowledgeChildrenQuery["order_field"];
  order_sort?: KnowledgeChildrenQuery["order_sort"];
}
export interface SpaceSearchPage {
  data: KnowledgeSpaceChild[];
  page: number;
  page_size: number;
  has_more: boolean;
}

function requireId(value: number): void {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new RangeError("Resource IDs must be positive safe integers");
  }
}
function spacePath(spaceId: number): string {
  requireId(spaceId);
  return `/api/v1/knowledge/space/${spaceId}`;
}
function itemPath(
  spaceId: number,
  kind: "files" | "folders",
  id: number,
): string {
  const path = spacePath(spaceId);
  requireId(id);
  return `${path}/${kind}/${id}`;
}

export async function listSpaceFolderParents(
  spaceId: number,
  folderId: number,
): Promise<SpaceFolderParent[]> {
  return axios.get(`${itemPath(spaceId, "folders", folderId)}/parent`);
}
export async function createSpaceFolder(
  spaceId: number,
  body: { name: string; parent_id?: number | null },
): Promise<KnowledgeSpaceChild> {
  const path = spacePath(spaceId);
  if (body.parent_id != null) requireId(body.parent_id);
  return axios.post(`${path}/folders`, {
    name: body.name,
    ...(body.parent_id === undefined ? {} : { parent_id: body.parent_id }),
  });
}
export async function renameSpaceFolder(
  spaceId: number,
  folderId: number,
  body: { name: string },
): Promise<KnowledgeSpaceChild> {
  return axios.put(itemPath(spaceId, "folders", folderId), { name: body.name });
}
export async function renameSpaceFile(
  spaceId: number,
  fileId: number,
  body: { name: string },
): Promise<KnowledgeSpaceChild> {
  return axios.put(itemPath(spaceId, "files", fileId), { name: body.name });
}
export async function getSpaceFilePreview(
  spaceId: number,
  fileId: number,
): Promise<SpaceFilePreview> {
  return axios.get(`${itemPath(spaceId, "files", fileId)}/preview`);
}
export async function getSpaceFileDownload(
  spaceId: number,
  fileId: number,
): Promise<SpaceFileUrls> {
  return axios.get(`${itemPath(spaceId, "files", fileId)}/download`);
}
export async function searchSpaceChildren(
  spaceId: number,
  query: SpaceSearchQuery,
): Promise<SpaceSearchPage> {
  const path = spacePath(spaceId);
  if (query.parent_id != null) requireId(query.parent_id);
  for (const id of query.tag_ids ?? []) requireId(id);
  const params: Record<string, unknown> = {
    page: query.page,
    page_size: query.page_size,
  };
  for (const key of [
    "keyword",
    "parent_id",
    "tag_ids",
    "file_status",
    "order_field",
    "order_sort",
  ] as const) {
    const value = query[key];
    if (value !== undefined)
      params[key] = Array.isArray(value) ? value.slice() : value;
  }
  return axios.get(`${path}/search`, {
    params,
    paramsSerializer: { indexes: null },
  });
}

export const knowledgeFilesApi = {
  listSpaceFolderParents,
  createSpaceFolder,
  renameSpaceFolder,
  renameSpaceFile,
  getSpaceFilePreview,
  getSpaceFileDownload,
  searchSpaceChildren,
};
export type KnowledgeFilesApi = typeof knowledgeFilesApi;
