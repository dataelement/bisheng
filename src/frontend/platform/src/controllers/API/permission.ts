import axios from "@/controllers/request"
import type { DepartmentSearchResult, DepartmentTreeNode } from "@/types/api/department"

export type PermissionSubjectType = "user" | "department" | "user_group"

export type PermissionResourceType =
  | "knowledge_space"
  | "knowledge_library"
  | "folder"
  | "knowledge_file"
  | "workflow"
  | "assistant"
  | "tool"
  | "channel"
  | "dashboard"
  | "linsight_skill"

export type PermissionActionLevel = 1 | 2 | 3 | 4
export type PermissionModelKind = "STANDARD" | "CUSTOM"
export type ResourcePermissionMode = "INHERIT" | "CUSTOM"
export type GrantMutationOperation = "ADD" | "MOVE" | "REMOVE"
export type PermissionSubjectKind = "user" | "department" | "user_group"

export interface PermissionCatalogAction {
  code: string
  name: string
  level: PermissionActionLevel | null
  active: boolean
  sort_order: number
  resource_types: PermissionResourceType[]
}

export interface PermissionCatalogModel {
  key: string
  name: string
  kind: PermissionModelKind
  config_scope: "PLATFORM"
  derived_level: PermissionActionLevel | null
  active: boolean
  allow_same_level: boolean
  action_codes: string[]
  version: number
}

export interface PermissionModelPreset {
  key: string
  name: string
  action_codes: string[]
}

export interface PermissionCatalogRelease {
  id: number
  release_key: string
  version: number
  status: string
  authorization_model_id: string
  checksum: string
  actions: PermissionCatalogAction[]
  models: PermissionCatalogModel[]
  presets?: PermissionModelPreset[]
  published_at?: string | null
}

export type PermissionCatalogChangeType =
  | "ASSIGN_ACTION_LEVEL"
  | "SET_ACTION_ACTIVE"
  | "CREATE_MODEL"
  | "UPDATE_MODEL"
  | "SET_MODEL_ACTIVE"
  | "DELETE_MODEL"
  | "SET_ALLOW_SAME_LEVEL"

export interface PermissionCatalogChange {
  type: PermissionCatalogChangeType
  action_code?: string
  level?: PermissionActionLevel | null
  model_key?: string
  name?: string
  action_codes?: string[]
  active?: boolean
  allow_same_level?: boolean
}

export interface CreatePermissionCatalogDraftRequest {
  idempotency_key: string
  base_release_id: number
  changes: PermissionCatalogChange[]
}

export interface PermissionCatalogImpact {
  checksum: string
  resource_count: number
  grant_count: number
  assignee_count: number
  expansion_count: number
  revocation_count: number
  blockers: string[]
  expires_at: string
}

export interface PermissionCatalogDraft {
  draft_id: number
  base_release_id: number
  impact: PermissionCatalogImpact
}

export interface PublishPermissionCatalogDraftRequest {
  expected_current_release_id: number
  idempotency_key: string
  confirmed: true
}

export interface PermissionCatalogPublishResult {
  release_id: number
  release_key: string
  status: string
  release_checksum: string
}

export interface GrantablePermissionModel {
  key: string
  name: string
  level: PermissionActionLevel | null
  active: boolean
}

export interface ResourcePermissionContext {
  mode: ResourcePermissionMode
  parent_type: PermissionResourceType | null
  parent_id: string | null
  resource_version: number
  catalog_release_id: number
  projection_state: string
  can_manage_permission: boolean
}

export interface PermissionGrantSubject {
  type: PermissionSubjectKind
  id: string
  name: string | null
}

export interface PermissionGrantSource {
  type: string
  include_children: boolean
}

export interface PermissionGrantAssignee {
  assignee_id: string
  assignee_version: number
  subject: PermissionGrantSubject
  model: GrantablePermissionModel
  source: PermissionGrantSource
  scope: "LOCAL" | "INHERITED"
  inherited_from: string | null
  inherited_from_name?: string | null
  protected: boolean
  editable: boolean
}

export interface PermissionGrantCursorPage {
  data: PermissionGrantAssignee[]
  page_size: number
  has_more: boolean
  next_cursor: string | null
}

export interface MyResourcePermissions {
  mode: ResourcePermissionMode
  actions: string[]
  sources: PermissionGrantSource[]
  roster_complete: boolean
}

export interface PermissionGrantSubjectInput {
  type: PermissionSubjectKind
  id: string
  userset_relation?: string | null
  include_children?: boolean
}

export type PermissionGrantMutationChange =
  | {
      op: "ADD"
      model_key: string
      subject: PermissionGrantSubjectInput
    }
  | {
      op: "MOVE"
      assignee_id: string
      expected_assignee_version: number
      target_model_key: string
    }
  | {
      op: "REMOVE"
      assignee_id: string
      expected_assignee_version: number
    }

export interface MutateResourceGrantsRequest {
  idempotency_key: string
  expected_resource_version: number
  expected_catalog_release_id: number
  changes: PermissionGrantMutationChange[]
}

export interface MutateResourceGrantsResult {
  resource_version: number
  items: PermissionGrantAssignee[]
}

export interface CreatePermissionModeDraftRequest {
  target_mode: ResourcePermissionMode
  expected_resource_version: number
  expected_catalog_release_id: number
}

export interface PermissionModeDraft {
  draft_id: string
  target_mode: ResourcePermissionMode
  impact_checksum: string
  affected_assignees: number
  expires_at: string
}

export interface ApplyPermissionModeDraftRequest {
  idempotency_key: string
  expected_resource_version: number
  expected_catalog_release_id: number
  confirmed: true
}

export interface ApplyPermissionModeDraftResult {
  applied: boolean
  mode: ResourcePermissionMode
  resource_version: number
}

export interface CheckResourceActionRequest {
  resource_type: PermissionResourceType
  resource_id: string
  action: string
}

function permissionResourcePath(
  resourceType: PermissionResourceType,
  resourceId: string,
): string {
  return `/api/v1/permissions/resources/${resourceType}/${resourceId}`
}

export async function getPermissionCatalogApi(): Promise<PermissionCatalogRelease> {
  return await axios.get(`/api/v1/permissions/catalog`)
}

export async function createPermissionCatalogDraftApi(
  payload: CreatePermissionCatalogDraftRequest,
): Promise<PermissionCatalogDraft> {
  return await axios.post(`/api/v1/permissions/catalog/drafts`, payload)
}

export async function getPermissionCatalogDraftApi(
  draftId: number,
): Promise<PermissionCatalogDraft> {
  return await axios.get(`/api/v1/permissions/catalog/drafts/${draftId}`)
}

export async function publishPermissionCatalogDraftApi(
  draftId: number,
  payload: PublishPermissionCatalogDraftRequest,
): Promise<PermissionCatalogPublishResult> {
  return await axios.post(
    `/api/v1/permissions/catalog/drafts/${draftId}/publish`,
    payload,
  )
}

export async function getGrantablePermissionModelsApi(
  resourceType: PermissionResourceType,
  resourceId: string,
): Promise<GrantablePermissionModel[]> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/grantable-models`,
  )
}

export async function getResourcePermissionContextApi(
  resourceType: PermissionResourceType,
  resourceId: string,
): Promise<ResourcePermissionContext> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/context`,
  )
}

export async function getResourcePermissionGrantsApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  params: { cursor?: string | null; page_size?: number } = {},
): Promise<PermissionGrantCursorPage> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/grants`,
    {
      params: {
        cursor: params.cursor ?? undefined,
        page_size: params.page_size ?? 50,
      },
    },
  )
}

export async function getMyResourcePermissionsApi(
  resourceType: PermissionResourceType,
  resourceId: string,
): Promise<MyResourcePermissions> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/my-permissions`,
  )
}

export async function mutateResourceGrantsApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  payload: MutateResourceGrantsRequest,
): Promise<MutateResourceGrantsResult> {
  return await axios.post(
    `${permissionResourcePath(resourceType, resourceId)}/grants:mutate`,
    payload,
  )
}

export async function createResourcePermissionModeDraftApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  payload: CreatePermissionModeDraftRequest,
): Promise<PermissionModeDraft> {
  return await axios.post(
    `${permissionResourcePath(resourceType, resourceId)}/mode-drafts`,
    payload,
  )
}

export async function applyResourcePermissionModeDraftApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  draftId: string,
  payload: ApplyPermissionModeDraftRequest,
): Promise<ApplyPermissionModeDraftResult> {
  return await axios.post(
    `${permissionResourcePath(resourceType, resourceId)}/mode-drafts/${draftId}/apply`,
    payload,
  )
}

export async function checkResourceActionApi(
  payload: CheckResourceActionRequest,
): Promise<{ allowed: boolean }> {
  return await axios.post(`/api/v1/permissions/check`, payload)
}

/**
 * Grant-subject pickers.
 *
 * These ask "who may I grant this resource to", so the resource is part of the
 * path and the predicate is `manage_permission` on it. Asking the
 * org-management endpoints instead — which answer "which users do I
 * administer" — left a space manager with an empty user list and a permission
 * error on the department tree.
 */

export interface GrantSubjectUser {
  user_id: number
  user_name: string
}

export interface GrantSubjectUserGroup {
  id: number
  name: string
}

// The department picker's tree renders whatever the org-management tree returns,
// so these endpoints answer in that same node shape and no adapter is needed.
export type GrantSubjectDepartment = DepartmentTreeNode

export async function getGrantSubjectUsersApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  params: { keyword?: string; page?: number; pageSize?: number } = {},
  config: { signal?: AbortSignal } = {},
): Promise<{ data: GrantSubjectUser[]; total: number }> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/users`,
    {
      params: {
        keyword: params.keyword ?? "",
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
      },
      signal: config.signal,
    },
  )
}

export async function getGrantSubjectUserGroupsApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  params: { keyword?: string; page?: number; pageSize?: number } = {},
): Promise<{ data: GrantSubjectUserGroup[]; total: number }> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/user-groups`,
    {
      params: {
        keyword: params.keyword ?? "",
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
      },
    },
  )
}

export async function getGrantSubjectDepartmentChildrenApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  parentId: number | null,
): Promise<GrantSubjectDepartment[]> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/departments/children`,
    { params: { parent_id: parentId ?? undefined } },
  )
}

export async function searchGrantSubjectDepartmentsApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  keyword: string,
): Promise<DepartmentSearchResult> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/departments/search`,
    { params: { keyword } },
  )
}

export async function getGrantSubjectDepartmentPathTreeApi(
  resourceType: PermissionResourceType,
  resourceId: string,
  deptId: number,
): Promise<DepartmentSearchResult> {
  return await axios.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/departments/${deptId}/path-tree`,
  )
}
