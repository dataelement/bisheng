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

export type PermissionAuthorizeItem = {
  subject_type: PermissionSubjectType
  subject_id: number
  relation: "owner" | "manager" | "editor" | "viewer"
  include_children?: boolean
}

export type PermissionEntry = {
  subject_type: PermissionSubjectType
  subject_id: number
  subject_name: string | null
  relation: "owner" | "manager" | "editor" | "viewer"
  include_children?: boolean
  inherited_from?: string
}

export async function getRebacSchemaApi(): Promise<{
  schema_version: string
  model_version: string
  types: RebacSchemaType[]
}> {
  return await axios.get(`/api/v1/permissions/rebac-schema`)
}

// Backward-compatible export for permission subject selectors.
export const getDepartmentTree = getDepartmentTreeApi

export async function getResourcePermissions(
  resourceType: string,
  resourceId: string
): Promise<PermissionEntry[]> {
  return await axios.get(`/api/v1/resources/${resourceType}/${resourceId}/permissions`)
}

export async function authorizeResource(
  resourceType: string,
  resourceId: string,
  grants: PermissionAuthorizeItem[],
  revokes: PermissionAuthorizeItem[]
): Promise<any> {
  return await axios.post(`/api/v1/resources/${resourceType}/${resourceId}/authorize`, {
    grants,
    revokes,
  })
}

export async function checkPermission(
  resourceType: string,
  resourceId: string,
  relation: PermissionRelation
): Promise<{ allowed: boolean }> {
  return await axios.post(`/api/v1/permissions/check`, {
    object_type: resourceType,
    object_id: resourceId,
    relation,
  })
}
