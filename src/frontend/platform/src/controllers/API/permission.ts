import type { GrantItem, PermissionEntry, RevokeItem } from "@/components/bs-comp/permission/types"
import axios from "@/controllers/request"
import type { DepartmentSearchResult, DepartmentTreeNode } from "@/types/api/department"

export type RebacSchemaType = {
  type: string
  relations: string[]
}

export type PermissionSubjectType = "user" | "department" | "user_group"

export type PermissionRelation =
  | "owner"
  | "manager"
  | "editor"
  | "viewer"
  | "can_manage"
  | "can_edit"
  | "can_read"
  | "can_delete"

export type GrantTier = "owner" | "manager" | "usage"

export type RelationModel = {
  id: string
  name: string
  relation: "owner" | "manager" | "editor" | "viewer"
  /** 后端未返回时按 relation 推断 */
  grant_tier?: GrantTier
  permissions: string[]
  permissions_explicit?: boolean
  is_system: boolean
}

export type PermissionTemplateItem = {
  id: string
  label: string
  relation: PermissionRelation
}

export type PermissionTemplateColumn = {
  title: string
  items: PermissionTemplateItem[]
}

export type PermissionTemplateSection = {
  title: string
  columns: PermissionTemplateColumn[]
}

export async function getRebacSchemaApi(): Promise<{
  schema_version: string
  model_version: string
  types: RebacSchemaType[]
}> {
  return await axios.get(`/api/v1/permissions/rebac-schema`)
}

export async function getKnowledgeSpacePermissionTemplateApi(): Promise<PermissionTemplateSection> {
  return await axios.get(`/api/v1/permissions/permission-templates/knowledge-space`)
}

export async function getApplicationPermissionTemplateApi(): Promise<PermissionTemplateSection> {
  return await axios.get(`/api/v1/permissions/permission-templates/application`)
}

export async function getKnowledgeLibraryPermissionTemplateApi(): Promise<PermissionTemplateSection> {
  return await axios.get(`/api/v1/permissions/permission-templates/knowledge-library`)
}

export async function getToolPermissionTemplateApi(): Promise<PermissionTemplateSection> {
  return await axios.get(`/api/v1/permissions/permission-templates/tool`)
}

export async function getChannelPermissionTemplateApi(): Promise<PermissionTemplateSection> {
  return await axios.get(`/api/v1/permissions/permission-templates/channel`)
}

export async function getResourcePermissions(
  resourceType: string,
  resourceId: string,
): Promise<PermissionEntry[]> {
  return await axios.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/permissions`,
  )
}

export async function authorizeResource(
  resourceType: string,
  resourceId: string,
  grants: (GrantItem & { model_id?: string })[],
  revokes: RevokeItem[],
): Promise<null> {
  return await axios.post(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/authorize`,
    { grants, revokes },
  )
}

export async function checkPermission(
  objectType: string,
  objectId: string,
  relation: string,
  permissionId?: string,
): Promise<{ allowed: boolean }> {
  // Run silent: the global response interceptor in @/controllers/request turns
  // any non-200 envelope into a red toast. For a first-time / non-admin user the
  // per-tool permission probe is supposed to come back with `{ allowed: false }`
  // (status 200), and a transient FGA error during a probe is not user-actionable.
  // Surfacing a "权限校验失败" toast in either case is what the first-time user
  // entering the API/MCP tools page sees today (gitee IKB0O4). The caller
  // (usePermissionIds) still records hasError / empty permissions and renders
  // the tool list without the "权限管理" button.
  return await axios.post(`/api/v1/permissions/check`, {
    object_type: objectType,
    object_id: objectId,
    relation,
    permission_id: permissionId,
  }, { silent: true } as any)
}

export async function getRelationModelsApi(): Promise<RelationModel[]> {
  return await axios.get(`/api/v1/permissions/relation-models`)
}

export async function getGrantableRelationModelsApi(
  objectType: string,
  objectId: string,
): Promise<RelationModel[]> {
  return await axios.get(`/api/v1/permissions/relation-models/grantable`, {
    params: { object_type: objectType, object_id: objectId },
  })
}

export async function getResourceGrantUsersApi(
  resourceType: string,
  resourceId: string,
  params?: { keyword?: string; page?: number; page_size?: number },
): Promise<any[]> {
  return await axios.get(`/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/users`, {
    params: {
      keyword: params?.keyword ?? "",
      page: params?.page ?? 1,
      page_size: params?.page_size ?? 1000,
    },
  })
}

// F038: lazy variants of the grant-subject department tree (browse one layer /
// server search / locate). Same authorization scope as the full-tree endpoint
// above (tenant subtree minus child-tenant mounts, optionally F033-narrowed),
// so a large org tree never loads at once. Used by the authorization pickers.

export async function getResourceGrantDepartmentChildrenApi(
  resourceType: string,
  resourceId: string,
  parentId: number | null,
): Promise<DepartmentTreeNode[]> {
  return await axios.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/departments/children`,
    { params: { parent_id: parentId ?? undefined } },
  )
}

export async function searchResourceGrantDepartmentsApi(
  resourceType: string,
  resourceId: string,
  keyword: string,
  limit = 50,
): Promise<DepartmentSearchResult> {
  return await axios.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/departments/search`,
    { params: { keyword, limit } },
  )
}

export async function getResourceGrantDepartmentPathTreeApi(
  resourceType: string,
  resourceId: string,
  deptInternalId: number,
): Promise<DepartmentSearchResult> {
  return await axios.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/departments/${deptInternalId}/path-tree`,
  )
}

export async function getResourceGrantUserGroupsApi(
  resourceType: string,
  resourceId: string,
  params?: { keyword?: string },
): Promise<any[]> {
  return await axios.get(`/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/user-groups`, {
    params: {
      keyword: params?.keyword ?? "",
    },
  })
}

export async function getKnowledgeSpaceGrantUsersApi(
  resourceId: string,
  params?: { keyword?: string; page?: number; page_size?: number },
): Promise<any[]> {
  return await getResourceGrantUsersApi("knowledge_space", resourceId, params)
}

export async function getKnowledgeSpaceGrantUserGroupsApi(
  resourceId: string,
  params?: { keyword?: string },
): Promise<any[]> {
  return await getResourceGrantUserGroupsApi("knowledge_space", resourceId, params)
}

export async function createRelationModelApi(payload: {
  name: string
  relation: "owner" | "manager" | "editor" | "viewer"
  permissions: string[]
}): Promise<{ id: string }> {
  return await axios.post(`/api/v1/permissions/relation-models`, payload)
}

export async function updateRelationModelApi(
  modelId: string,
  payload: { name?: string; permissions?: string[] },
): Promise<null> {
  return await axios.put(`/api/v1/permissions/relation-models/${modelId}`, payload)
}

export async function deleteRelationModelApi(modelId: string): Promise<null> {
  return await axios.delete(`/api/v1/permissions/relation-models/${modelId}`)
}
