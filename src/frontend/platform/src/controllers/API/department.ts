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

export async function getDepartmentAssignableRolesApi(
  deptId: string
): Promise<{ id: number; role_name: string; role_type: string; department_id?: number | null }[]> {
  return await axios.get(`/api/v1/departments/${deptId}/assignable-roles`)
}

export async function createDepartmentLocalMemberApi(
  deptId: string,
  data: { user_name: string; password: string; role_ids: number[] }
): Promise<{ user_id: number; user_name: string; person_id: string; dept_id: string }> {
  return await axios.post(`/api/v1/departments/${deptId}/local-members`, data)
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
