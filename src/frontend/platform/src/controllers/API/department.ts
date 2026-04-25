import axios from "@/controllers/request"
import {
  DepartmentAdmin,
  DepartmentCreateForm,
  DepartmentDetail,
  DepartmentMember,
  DepartmentTreeNode,
  DepartmentUpdateForm,
} from "@/types/api/department"

/** dept_id 常含 `BS@...`，必须编码进 URL path，否则部分代理/网关会误解析成 404 */
function depSeg(deptId: string): string {
  return encodeURIComponent(deptId)
}

// ── Tree ───────────────────────────────────────────────

export async function getDepartmentTreeApi(): Promise<DepartmentTreeNode[]> {
  return await axios.get(`/api/v1/departments/tree`)
}

// ── CRUD ───────────────────────────────────────────────

export async function createDepartmentApi(
  data: DepartmentCreateForm
): Promise<any> {
  return await axios.post(`/api/v1/departments/`, data)
}

export async function getDepartmentApi(
  deptId: string
): Promise<DepartmentDetail> {
  return await axios.get(`/api/v1/departments/${depSeg(deptId)}`)
}

export async function updateDepartmentApi(
  deptId: string,
  data: DepartmentUpdateForm
): Promise<any> {
  return await axios.put(`/api/v1/departments/${depSeg(deptId)}`, data)
}

export async function deleteDepartmentApi(deptId: string): Promise<any> {
  return await axios.delete(`/api/v1/departments/${depSeg(deptId)}`)
}

export async function purgeDepartmentApi(deptId: string): Promise<any> {
  return await axios.delete(`/api/v1/departments/${depSeg(deptId)}/purge`)
}

export async function restoreDepartmentApi(deptId: string): Promise<any> {
  return await axios.post(`/api/v1/departments/${depSeg(deptId)}/restore`)
}

// ── Mount as Child Tenant ──────────────────────────────
// mount-tenant uses the integer PK (not the BS@... business id) per
// `MountTenantRequest` on the backend; see tenant_mount.py:79.

export interface MountTenantPayload {
  tenant_code: string
  tenant_name: string
}

export async function mountTenantApi(
  deptIdInt: number,
  data: MountTenantPayload
): Promise<{ id: number; tenant_code: string; tenant_name: string; parent_tenant_id: number; status: string }> {
  return await axios.post(`/api/v1/departments/${deptIdInt}/mount-tenant`, data)
}

/** v2.5.1 收窄到唯一路径：资源迁回 Root + Child 归档。
 *
 * Returns ``migrated_counts`` mapping table → row count moved into Root.
 */
export async function unmountTenantApi(
  deptIdInt: number,
): Promise<{ tenant_id: number; migrated_counts: Record<string, number> }> {
  return await axios.delete(`/api/v1/departments/${deptIdInt}/mount-tenant`)
}

// ── Move ───────────────────────────────────────────────

export async function moveDepartmentApi(
  deptId: string,
  newParentId: number
): Promise<any> {
  return await axios.post(`/api/v1/departments/${depSeg(deptId)}/move`, {
    new_parent_id: newParentId,
  })
}

// ── Members ────────────────────────────────────────────

export async function getDepartmentMembersApi(
  deptId: string,
  params: {
    page: number
    limit: number
    keyword?: string
    is_primary?: number
  }
): Promise<{ data: DepartmentMember[]; total: number }> {
  return await axios.get(`/api/v1/departments/${depSeg(deptId)}/members`, { params })
}

/** 全组织成员搜索（主属部门路径），可见范围与部门树一致 */
export interface GlobalMemberSearchRow {
  user_id: number
  user_name: string
  primary_department_dept_id: string
  primary_department_path: string
}

export async function searchGlobalMembersApi(params: {
  keyword: string
  page?: number
  limit?: number
}): Promise<{ data: GlobalMemberSearchRow[]; total: number }> {
  return await axios.get(`/api/v1/departments/search/global-members`, {
    params: {
      keyword: params.keyword,
      page: params.page ?? 1,
      limit: params.limit ?? 20,
    },
  })
}

export async function addDepartmentMembersApi(
  deptId: string,
  data: { user_ids: number[]; is_primary: number }
): Promise<any> {
  return await axios.post(`/api/v1/departments/${depSeg(deptId)}/members`, data)
}

export async function removeDepartmentMemberApi(
  deptId: string,
  userId: number
): Promise<any> {
  return await axios.delete(`/api/v1/departments/${depSeg(deptId)}/members/${userId}`)
}

export type DepartmentMemberEditMode = "affiliate" | "local_primary" | "synced_primary"

export type DepartmentMemberEditForm = {
  edit_mode: DepartmentMemberEditMode
  user: {
    user_id: number
    user_name: string
    person_id: string
    source: string
  }
  context: { dept_id: string; name: string; is_primary: number }
  primary_department: null | {
    id: number
    dept_id: string
    name: string
    role_ids: number[]
  }
  can_change_primary: boolean
  affiliate_rows: { dept_id: string; name: string; role_ids: number[] }[]
  assignable_roles_catalog: Record<
    string,
    { id: number; role_name: string; role_type?: string; department_id?: number | null }[]
  >
  context_role_ids: number[]
  manageable_groups: { id: number; group_name: string; visibility?: string }[]
  current_group_ids: number[]
}

export async function getDepartmentMemberEditFormApi(
  deptId: string,
  userId: number
): Promise<DepartmentMemberEditForm> {
  return await axios.get(
    `/api/v1/departments/${depSeg(deptId)}/members/${userId}/edit-form`
  )
}

export async function applyDepartmentMemberEditApi(
  deptId: string,
  userId: number,
  body: {
    user_name?: string | null
    primary_department_id?: number | null
    group_ids?: number[] | null
    context_role_ids?: number[] | null
    primary_role_ids?: number[] | null
    affiliate_roles?: { dept_id: string; role_ids: number[] }[] | null
  }
): Promise<void> {
  await axios.post(
    `/api/v1/departments/${depSeg(deptId)}/members/${userId}/apply-edit`,
    body
  )
}

export async function checkDepartmentMemberDeleteApi(
  deptId: string,
  userId: number
): Promise<{
  has_assets: boolean
  counts: { knowledge_spaces: number; flows: number; assistants: number }
}> {
  return await axios.get(
    `/api/v1/departments/${depSeg(deptId)}/members/${userId}/delete-check`
  )
}

export async function deleteDepartmentLocalMemberApi(
  deptId: string,
  userId: number
): Promise<void> {
  await axios.delete(
    `/api/v1/departments/${depSeg(deptId)}/members/${userId}/local-account`
  )
}

export async function getDepartmentAssignableRolesApi(
  deptId: string
): Promise<{ id: number; role_name: string; role_type: string; department_id?: number | null }[]> {
  return await axios.get(`/api/v1/departments/${depSeg(deptId)}/assignable-roles`)
}

export async function createDepartmentLocalMemberApi(
  deptId: string,
  data: { user_name: string; person_id: string; password: string; role_ids: number[] }
): Promise<{ user_id: number; user_name: string; person_id: string; dept_id: string }> {
  // dept_id 放 body，避免路径含 BS@ 时部分网关/反代误解析为 404（与 POST .../{dept_id}/local-members 等价）
  return await axios.post(`/api/v1/departments/local-members`, {
    dept_id: deptId,
    ...data,
  })
}

// ── Admins ─────────────────────────────────────────────

export async function getDepartmentAdminsApi(
  deptId: string
): Promise<DepartmentAdmin[]> {
  return await axios.get(`/api/v1/departments/${depSeg(deptId)}/admins`)
}

export async function setDepartmentAdminsApi(
  deptId: string,
  userIds: number[]
): Promise<DepartmentAdmin[]> {
  return await axios.put(`/api/v1/departments/${depSeg(deptId)}/admins`, {
    user_ids: userIds,
  })
}
