import axios from "../request";

export interface DepartmentKnowledgeSpaceSummary {
  id: number;
  name: string;
  department_id?: number | null;
  department_name?: string | null;
  space_kind?: "normal" | "department";
  auth_type?: string;
  is_released?: boolean;
  is_hidden?: boolean;
  // F045: the single space admin; pending_admin=true means the space has no
  // valid admin and admin-gated operations are locked until one is assigned.
  admin_user_id?: number | null;
  admin_user_name?: string | null;
  pending_admin?: boolean | null;
}

export interface DepartmentKnowledgeSpaceCreateItem {
  department_id: number;
  // F045: required — every department knowledge space is created with exactly
  // one space admin; the backend rejects items without one (18003).
  admin_user_id: number;
}

export async function getDepartmentKnowledgeSpacesApi(params?: {
  order_by?: "name" | "update_time";
  include_hidden?: boolean;
}): Promise<DepartmentKnowledgeSpaceSummary[]> {
  return await axios.get(`/api/v1/knowledge/space/department/all`, { params });
}

export async function batchCreateDepartmentKnowledgeSpacesApi(
  items: DepartmentKnowledgeSpaceCreateItem[],
): Promise<DepartmentKnowledgeSpaceSummary[]> {
  return await axios.post(`/api/v1/knowledge/space/department/batch-create`, { items });
}

// F045: atomically replace the single space admin (super admin only).
export async function replaceDepartmentSpaceAdminApi(
  departmentId: number,
  adminUserId: number,
): Promise<DepartmentKnowledgeSpaceSummary> {
  return await axios.put(`/api/v1/knowledge/space/department/${departmentId}/admin`, {
    admin_user_id: adminUserId,
  });
}

// Hide (is_hidden=true) or restore (is_hidden=false) department knowledge spaces
// from the management list. Data, files and member permissions are preserved.
export async function setDepartmentKnowledgeSpacesVisibilityApi(
  departmentIds: number[],
  isHidden: boolean,
): Promise<{ changed: number }> {
  return await axios.post(`/api/v1/knowledge/space/department/visibility`, {
    department_ids: departmentIds,
    is_hidden: isHidden,
  });
}
