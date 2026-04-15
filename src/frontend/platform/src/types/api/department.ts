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
  department_id: number
  is_primary: number
  source: string
  create_time: string
  update_time?: string
  enabled: boolean
  user_groups: { id: number; group_name: string }[]
  roles: { id: number; role_name: string }[]
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
