export interface DepartmentTreeNode {
  id: number
  dept_id: string
  name: string
  parent_id: number | null
  path: string
  sort_order: number
  source: string
  status: string
  member_count: number
  children: DepartmentTreeNode[]
}

export interface DepartmentAdmin {
  user_id: number
  user_name: string
}

export interface DepartmentDetail {
  id: number
  dept_id: string
  name: string
  parent_id: number | null
  path: string
  sort_order: number
  source: string
  status: string
  default_role_ids: number[] | null
  member_count: number
}

export interface DepartmentMember {
  user_id: number
  user_name: string
  /** 本地人员 ID（external_id），用于重名展示；非展示字段 */
  person_id?: string | null
  department_id: number
  is_primary: number
  source: string
  create_time: string
  update_time?: string
  enabled: boolean
  user_groups: { id: number; group_name: string }[]
  roles: { id: number; role_name: string }[]
  /** 当前部门 OpenFGA admin；用于在角色列最前展示「部门管理员」 */
  is_department_admin?: boolean
}

export interface DepartmentCreateForm {
  name: string
  parent_id: number
  sort_order?: number
  default_role_ids?: number[]
  admin_user_ids?: number[]
}

export interface DepartmentUpdateForm {
  name?: string
  sort_order?: number
  default_role_ids?: number[]
}
