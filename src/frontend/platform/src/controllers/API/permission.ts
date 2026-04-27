import type { GrantItem, PermissionEntry, RevokeItem } from "@/components/bs-comp/permission/types"
import axios from "@/controllers/request"

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
  return await axios.post(`/api/v1/permissions/check`, {
    object_type: objectType,
    object_id: objectId,
    relation,
    permission_id: permissionId,
  })
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

export async function getResourceGrantDepartmentsApi(
  resourceType: string,
  resourceId: string,
): Promise<any[]> {
  return await axios.get(`/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/departments`)
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

export async function getKnowledgeSpaceGrantDepartmentsApi(
  resourceId: string,
): Promise<any[]> {
  return await getResourceGrantDepartmentsApi("knowledge_space", resourceId)
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
