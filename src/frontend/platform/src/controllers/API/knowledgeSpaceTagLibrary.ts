import axios from "@/controllers/request"

export interface KnowledgeSpaceTagLibraryListItem {
  id: number
  name: string
  description?: string | null
  tag_count: number
  is_builtin: boolean
}

export interface KnowledgeSpaceTagListItem {
  tag_name: string
  resource_type: string
  resource_count: number
}

export interface KnowledgeSpaceTagDetail extends KnowledgeSpaceTagListItem {
  tags: string[]
}

export interface KnowledgeSpaceTagPage {
  data: KnowledgeSpaceTagListItem[]
  status_code: number
  status_message: string
}

export interface KnowledgeSpaceTagListPage {
  data: KnowledgeSpaceTagListItem[]
  total: number
}

export async function getKnowledgeSpaceTagListApi(params?: {
  page?: number
  page_size?: number
  keyword?: string
}): Promise<KnowledgeSpaceTagListPage> {
  return await axios.post("/api/v1/workstation/tags/list_tags", params)
}

export async function deleteKnowledgeSpaceTagApi(
  data:{
    tag_name: string,
    resource_type: string
  }): Promise<boolean> {
  return await axios.post(`/api/v1/workstation/tags/delete`, data)
}

export async function createKnowledgeSpaceTagApi(data: {
  tag_name: string
  resource_type: string
}): Promise<KnowledgeSpaceTagDetail> {
  return await axios.post("/api/v1/workstation/tags/create", data)
}

export async function updateKnowledgeSpaceTagApi(
  data: {
    original_tag_name: string
    tag_name: string
    resource_type: string
  },
): Promise<KnowledgeSpaceTagDetail> {
  return await axios.post(`/api/v1/workstation/tags/update`, data)
}

export interface KnowledgeSpaceTagLibraryDetail extends KnowledgeSpaceTagLibraryListItem {
  tags: string[]
}

export interface KnowledgeSpaceTagLibraryPage {
  data: KnowledgeSpaceTagLibraryListItem[]
  total: number
}

export async function getKnowledgeSpaceTagLibrariesApi(params?: {
  page?: number
  page_size?: number
  keyword?: string
}): Promise<KnowledgeSpaceTagLibraryPage> {
  return await axios.get("/api/v1/knowledge/space/tag-libraries", { params })
}

export async function getKnowledgeSpaceTagLibraryApi(id: number): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.get(`/api/v1/knowledge/space/tag-libraries/${id}`)
}

export async function createKnowledgeSpaceTagLibraryApi(data: {
  name: string
  description?: string
  tags: string[]
  is_builtin?: boolean
}): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.post("/api/v1/knowledge/space/tag-libraries", data)
}

export async function updateKnowledgeSpaceTagLibraryApi(
  id: number,
  data: {
    name?: string
    description?: string
    tags?: string[]
  },
): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.put(`/api/v1/knowledge/space/tag-libraries/${id}`, data)
}

export async function deleteKnowledgeSpaceTagLibraryApi(id: number): Promise<boolean> {
  return await axios.delete(`/api/v1/knowledge/space/tag-libraries/${id}`)
}

export async function getKnowledgeSpaceTagLibraryUsageApi(id: number): Promise<{ count: number }> {
  return await axios.get(`/api/v1/knowledge/space/tag-libraries/${id}/usage`)
}

// Review tag APIs
export interface ReviewTagResourceItem {
  file_source?: string
  file_name?: string
  submit_time?: string
  [key: string]: any
}

export interface ReviewTagItem {
  tag_name: string
  resource_type: string
  tags_total: number
  resource_files: ReviewTagResourceItem[]
}

export interface ReviewTagPage {
  data: ReviewTagItem[]
  total: number
}

export async function getKnowledgeSpaceReviewTagListApi(params: {
  page: number
  page_size: number
}): Promise<ReviewTagPage> {
  return await axios.post("/api/v1/workstation/tags/list_review", params)
}

export async function approveOrRejectReviewTagApi(data: {
  tag_name: string
  status: number
  resource_type: string
  reject_reason?: string
}): Promise<boolean> {
  return await axios.post("/api/v1/workstation/tags/approve_or_reject", data)
}

export async function deleteReviewTagApi(data: {
  tag_name: string
  resource_type: string
}): Promise<boolean> {
  return await axios.post("/api/v1/workstation/tags/delete_review", data)
}
