import { GrantItem, PermissionEntry, ResourceType, RevokeItem } from "@/components/bs-comp/permission/types"
import axios from "../request"

export async function checkPermission(
  objectType: ResourceType,
  objectId: string,
  relation: string,
): Promise<{ allowed: boolean }> {
  return await axios.post('/api/v1/permissions/check', {
    object_type: objectType,
    object_id: objectId,
    relation,
  })
}

export async function getResourcePermissions(
  resourceType: ResourceType,
  resourceId: string,
): Promise<PermissionEntry[]> {
  return await axios.get(`/api/v1/permissions/resources/${resourceType}/${resourceId}/permissions`)
}

export async function authorizeResource(
  resourceType: ResourceType,
  resourceId: string,
  grants: GrantItem[],
  revokes: RevokeItem[],
): Promise<null> {
  return await axios.post(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/authorize`,
    { grants, revokes },
  )
}

export async function getAccessibleObjects(
  objectType: ResourceType,
  relation: string = 'can_read',
): Promise<string[] | null> {
  return await axios.get('/api/v1/permissions/objects', {
    params: { object_type: objectType, relation },
  })
}

export async function getDepartmentTree(): Promise<any[]> {
  return await axios.get('/api/v1/departments/tree')
}
