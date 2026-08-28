import axios from "@/controllers/request"

export interface KnowledgeSpaceTagLibraryListItem {
  id: number
  name: string
  description?: string | null
  tag_count: number
  bound_space_count?: number
  bound_space_names?: string[]
  used_knowledge_count?: number
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
  data: {
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

export interface KnowledgeSpaceTagLibraryTagItem {
  name: string
  resource_type: string
  resource_count?: number
  create_time?: string | null
  creator_name?: string | null
}

export interface KnowledgeSpaceTagLibraryDetail extends KnowledgeSpaceTagLibraryListItem {
  tags: string[]
  tag_items?: KnowledgeSpaceTagLibraryTagItem[]
}

export interface KnowledgeSpaceTagLibraryPage {
  data: KnowledgeSpaceTagLibraryListItem[]
  total: number
}

export interface KnowledgeSpaceTagLibraryTreeItem {
  id: string
  name: string
  key: number
  library_id: number
  meta_info: string | null
  parent_id: string | null
  children: KnowledgeSpaceTagLibraryTreeItem[]
}

export async function getKnowledgeSpaceTagLibrariesApi(params?: {
  page?: number
  page_size?: number
  keyword?: string
}): Promise<KnowledgeSpaceTagLibraryPage> {
  return await axios.get("/api/v1/knowledge/space/tag-libraries", { params })
}

export async function getKnowledgeSpaceTagLibrariesByTreeApi(params?: {
  keyword?: string
}): Promise<KnowledgeSpaceTagLibraryTreeItem[]> {
  return await axios.get("/api/v1/knowledge/space/tag-libraries/tree", { params })
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
    manual_tags?: string[]
    ai_tags?: string[]
  },
): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.put(`/api/v1/knowledge/space/tag-libraries/${id}`, data)
}

export async function deleteKnowledgeSpaceTagLibraryTagApi(
  id: number,
  data: {
    tag_name: string
    resource_type: string
  },
): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.delete(`/api/v1/knowledge/space/tag-libraries/${id}/tags`, { params: data })
}

export async function deleteKnowledgeSpaceTagLibraryApi(id: number): Promise<boolean> {
  return await axios.delete(`/api/v1/knowledge/space/tag-libraries/${id}`)
}

export async function getKnowledgeSpaceTagLibraryUsageApi(id: number): Promise<{ count: number }> {
  return await axios.get(`/api/v1/knowledge/space/tag-libraries/${id}/usage`)
}

/** One knowledge space attached to a tag library. */
export interface TagLibraryBoundKnowledge {
  id: number
  name: string
  /** public | department | team | team_ks | personal; null for spaces with no scope row. */
  level?: string | null
}

/**
 * Move a library between the two it was dropped between.
 *
 * Neighbour ids rather than an index, so the server writes only the moved row.
 * Pass null at the ends of the list.
 */
export async function reorderKnowledgeSpaceTagLibraryApi(
  id: number,
  neighbours: { prev_library_id: number | null; next_library_id: number | null },
): Promise<boolean> {
  return await axios.post(`/api/v1/knowledge/space/tag-libraries/${id}/sort`, neighbours)
}

export async function getKnowledgeSpaceTagLibraryKnowledgesApi(
  id: number,
): Promise<TagLibraryBoundKnowledge[]> {
  return await axios.get(`/api/v1/knowledge/space/tag-libraries/${id}/knowledges`)
}

export async function addKnowledgeSpaceTagLibraryKnowledgesApi(
  id: number,
  knowledgeIds: number[],
): Promise<{ added: number[] }> {
  return await axios.post(`/api/v1/knowledge/space/tag-libraries/${id}/knowledges`, {
    knowledge_ids: knowledgeIds,
  })
}

export async function removeKnowledgeSpaceTagLibraryKnowledgeApi(
  id: number,
  knowledgeId: number,
): Promise<boolean> {
  return await axios.delete(`/api/v1/knowledge/space/tag-libraries/${id}/knowledges/${knowledgeId}`)
}

// Review tag APIs
export interface ReviewTagResourceItem {
  file_source?: string
  file_name?: string
  file_id?: number
  id?: number
  submit_time?: string
  knowledge_id?: number
  /** Immediate parent folder id for portal deep-link navigation. */
  parent_id?: number | null
  file_url?: string
  [key: string]: any
}

export interface ReviewTagItem {
  tag_name: string
  resource_type: string
  tags_total: number
  resource_files: ReviewTagResourceItem[]
  knowledge_ids?: number[]
  /** Present when the pending tag is scoped to a tag library. */
  tag_library_id?: number | null
}

export interface ReviewTagPage {
  data: ReviewTagItem[]
  total: number
}

export async function getKnowledgeSpaceReviewTagListApi(params: {
  page: number
  page_size: number
  keyword?: string
}): Promise<ReviewTagPage> {
  return await axios.post("/api/v1/workstation/tags/list_review", params)
}

export async function getKnowledgeSpaceTagLibrariesByKnowledgeApi(
  knowledgeId: number,
): Promise<KnowledgeSpaceTagLibraryListItem[]> {
  return await axios.get(`/api/v1/knowledge/space/tag-libraries/by-knowledge/${knowledgeId}`)
}

export async function approveOrRejectReviewTagApi(data: {
  tag_name: string
  status: number
  resource_type: string
  reject_reason?: string
  tag_library_id?: number
  knowledge_id?: number
  ack_similar?: boolean
  skip_blacklist?: boolean
}): Promise<boolean> {
  return await axios.post("/api/v1/workstation/tags/approve_or_reject", data)
}

export interface ReviewTagSimilarMatchItem {
  name: string
  match_kind: "exact" | "substring" | "similarity" | string
  score?: number | null
}

export interface ReviewTagSimilarCheckResult {
  exact_matches: ReviewTagSimilarMatchItem[]
  similar_matches: ReviewTagSimilarMatchItem[]
  similarity_threshold?: number
}

export async function checkReviewTagSimilarApi(data: {
  tag_name: string
  tag_library_id: number
}): Promise<ReviewTagSimilarCheckResult> {
  return await axios.post("/api/v1/workstation/tags/review_similar_check", data)
}

export interface ReviewTagSimilarBatchItem {
  tag_name: string
  exact_matches: ReviewTagSimilarMatchItem[]
  similar_matches: ReviewTagSimilarMatchItem[]
}

export interface ReviewTagSimilarBatchCheckResult {
  items: ReviewTagSimilarBatchItem[]
  similar_tag_count: number
  similarity_threshold?: number
}

export async function checkReviewTagSimilarBatchApi(data: {
  tag_names: string[]
  tag_library_id: number
}): Promise<ReviewTagSimilarBatchCheckResult> {
  return await axios.post("/api/v1/workstation/tags/review_similar_check_batch", data)
}

export async function deleteReviewTagApi(data: {
  tag_name: string
  resource_type: string
}): Promise<boolean> {
  return await axios.post("/api/v1/workstation/tags/delete_review", data)
}

// ---------------------------------------------------------------------------
// F079 tag management console
//
// Library mode keys rows by tag id. Review mode keys them by
// (name, resource_type): one tag name produced in several knowledge spaces
// creates one review_tag row per space, and the whole review flow treats that
// pair as a single unit.
// ---------------------------------------------------------------------------

/**
 * Row status, plus one filter-only value.
 *
 * "approved" rows are read back from the tag library rather than review_tag —
 * approving deletes the review row. "reviewed" is only ever sent as a filter
 * (the 已审核 tab: approved and rejected together) and never comes back on a row.
 */
export type TagConsoleReviewStatus = "pending" | "rejected" | "approved"
export type TagConsoleReviewFilterStatus = TagConsoleReviewStatus | "reviewed"

export interface TagConsoleSourceFile {
  file_id: number
  file_name: string
  knowledge_id: number
  /** 标签来源库 — the knowledge base this file lives in. */
  knowledge_name?: string | null
  parent_id?: number | null
  /** knowledge_file.status; 7 means it failed the content-safety check. */
  status?: number | null
  /** JSON for a content-safety rejection, carrying the words that were hit. */
  remark?: string | null
}

export interface TagConsoleFilterParams {
  tag_name?: string
  resource_type?: string
  /** 标签来源库 — matched through the tag's file links, not stored on the tag. */
  source_knowledge_id?: number
  submitter_id?: number
  reviewer_id?: number
  create_time_start?: string
  create_time_end?: string
  review_time_start?: string
  review_time_end?: string
  page?: number
  page_size?: number
}

export interface TagConsoleItem {
  id: number
  name: string
  resource_type: string
  library_id?: number | null
  library_name?: string | null
  marked_knowledge_count: number
  submitter_id?: number | null
  submitter_name?: string | null
  reviewer_id?: number | null
  reviewer_name?: string | null
  source_files: TagConsoleSourceFile[]
  create_time?: string | null
  review_time?: string | null
}

export interface TagConsoleReviewRef {
  name: string
  resource_type: string
}

export interface TagConsoleReviewItem extends TagConsoleReviewRef {
  status: TagConsoleReviewStatus
  review_tag_count: number
  library_id?: number | null
  library_name?: string | null
  submitter_id?: number | null
  submitter_name?: string | null
  reviewer_id?: number | null
  reviewer_name?: string | null
  source_files: TagConsoleSourceFile[]
  create_time?: string | null
  review_time?: string | null
  reject_reason?: string | null
}

export interface TagConsoleBatchResult {
  succeeded: number
  skipped: number
  failed: { name: string; reason: string }[]
}

export async function searchTagConsoleApi(
  params: TagConsoleFilterParams & { library_ids?: number[] },
): Promise<{ data: TagConsoleItem[]; total: number }> {
  return await axios.post("/api/v1/workstation/tags/console/search", params)
}

export async function createTagConsoleTagApi(data: {
  tag_name: string
  library_id: number
}): Promise<TagConsoleItem> {
  return await axios.post("/api/v1/workstation/tags/console/create", data)
}

export async function batchDeleteTagConsoleApi(ids: number[]): Promise<TagConsoleBatchResult> {
  return await axios.post("/api/v1/workstation/tags/console/batch-delete", { ids })
}

export async function batchMoveTagConsoleApi(
  ids: number[],
  targetLibraryId: number,
): Promise<TagConsoleBatchResult> {
  return await axios.post("/api/v1/workstation/tags/console/batch-move", {
    ids,
    target_library_id: targetLibraryId,
  })
}

export async function searchTagConsoleReviewApi(
  params: TagConsoleFilterParams & { status?: TagConsoleReviewFilterStatus | null },
): Promise<{
  data: TagConsoleReviewItem[]
  total: number
  pending_count: number
  rejected_count: number
  approved_count: number
}> {
  return await axios.post("/api/v1/workstation/tags/console/review/search", params)
}

export async function getTagConsoleReviewDetailApi(
  ref: TagConsoleReviewRef,
): Promise<TagConsoleReviewItem> {
  return await axios.post("/api/v1/workstation/tags/console/review/detail", ref)
}

export async function batchApproveTagConsoleApi(
  items: TagConsoleReviewRef[],
  targetLibraryId: number,
  ackSimilar = false,
): Promise<TagConsoleBatchResult> {
  return await axios.post("/api/v1/workstation/tags/console/review/batch-approve", {
    items,
    target_library_id: targetLibraryId,
    ack_similar: ackSimilar,
  })
}

export async function batchRejectTagConsoleApi(
  items: TagConsoleReviewRef[],
  rejectReason: string,
  skipBlacklist = false,
): Promise<TagConsoleBatchResult> {
  return await axios.post("/api/v1/workstation/tags/console/review/batch-reject", {
    items,
    reject_reason: rejectReason,
    skip_blacklist: skipBlacklist,
  })
}

export interface TagBlacklistItem {
  id: number
  name: string
  user_id?: number
  create_time?: string | null
}

export interface TagBlacklistSearchResp {
  data: TagBlacklistItem[]
  total: number
  count: number
  limit: number
}

export interface TagBlacklistPreviewResp {
  count: number
  limit: number
  new_count: number
  would_exceed: boolean
}

export async function searchTagBlacklistApi(params: {
  keyword?: string
  page?: number
  page_size?: number
}): Promise<TagBlacklistSearchResp> {
  return await axios.get("/api/v1/workstation/tags/console/blacklist", { params })
}

export async function previewTagBlacklistApi(names: string[]): Promise<TagBlacklistPreviewResp> {
  return await axios.post("/api/v1/workstation/tags/blacklist/preview", { names })
}

export async function addTagBlacklistApi(name: string): Promise<TagBlacklistItem> {
  return await axios.post("/api/v1/workstation/tags/console/blacklist", { name })
}

export async function deleteTagBlacklistApi(id: number): Promise<boolean> {
  return await axios.delete(`/api/v1/workstation/tags/console/blacklist/${id}`)
}

export async function getTagConsolePendingCountApi(): Promise<{ pending_count: number }> {
  return await axios.get("/api/v1/workstation/tags/console/review/pending-count")
}

export interface TagConsoleSourceKnowledge {
  id: number
  name: string
}

/**
 * Options for the 标签来源库 filter: only knowledge bases that actually produced
 * a tag, distinct by id and without 『我的收藏』.
 */
export async function listTagConsoleSourceKnowledgesApi(
  keyword?: string,
): Promise<{ data: TagConsoleSourceKnowledge[] }> {
  return await axios.get("/api/v1/workstation/tags/console/source-knowledges", {
    params: keyword ? { keyword } : {},
  })
}
