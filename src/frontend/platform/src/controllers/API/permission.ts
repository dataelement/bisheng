import type { GrantItem, PermissionEntry, RevokeItem } from "@/components/bs-comp/permission/types"
import axios from "@/controllers/request"
import { getDepartmentTreeApi } from "@/controllers/API/department"

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

export const getDepartmentTree = getDepartmentTreeApi

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
): Promise<{ allowed: boolean }> {
  return await axios.post(`/api/v1/permissions/check`, {
    object_type: objectType,
    object_id: objectId,
    relation,
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
