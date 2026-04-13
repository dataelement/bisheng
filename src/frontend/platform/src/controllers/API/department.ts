import axios from "@/controllers/request"
import {
  DepartmentAdmin,
  DepartmentCreateForm,
  DepartmentDetail,
  DepartmentMember,
  DepartmentTreeNode,
  DepartmentUpdateForm,
} from "@/types/api/department"

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
  return await axios.get(`/api/v1/departments/${deptId}`)
}

export async function updateDepartmentApi(
  deptId: string,
  data: DepartmentUpdateForm
): Promise<any> {
  return await axios.put(`/api/v1/departments/${deptId}`, data)
}

export async function deleteDepartmentApi(deptId: string): Promise<any> {
  return await axios.delete(`/api/v1/departments/${deptId}`)
}

// ── Move ───────────────────────────────────────────────

export async function moveDepartmentApi(
  deptId: string,
  newParentId: number
): Promise<any> {
  return await axios.post(`/api/v1/departments/${deptId}/move`, {
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
  return await axios.get(`/api/v1/departments/${deptId}/members`, { params })
}

export async function addDepartmentMembersApi(
  deptId: string,
  data: { user_ids: number[]; is_primary: number }
): Promise<any> {
  return await axios.post(`/api/v1/departments/${deptId}/members`, data)
}

export async function removeDepartmentMemberApi(
  deptId: string,
  userId: number
): Promise<any> {
  return await axios.delete(`/api/v1/departments/${deptId}/members/${userId}`)
}

// ── Admins ─────────────────────────────────────────────

export async function getDepartmentAdminsApi(
  deptId: string
): Promise<DepartmentAdmin[]> {
  return await axios.get(`/api/v1/departments/${deptId}/admins`)
}

export async function setDepartmentAdminsApi(
  deptId: string,
  userIds: number[]
): Promise<DepartmentAdmin[]> {
  return await axios.put(`/api/v1/departments/${deptId}/admins`, {
    user_ids: userIds,
  })
}
