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
}

export async function getDepartmentKnowledgeSpacesApi(params?: {
  order_by?: "name" | "update_time";
  include_hidden?: boolean;
}): Promise<DepartmentKnowledgeSpaceSummary[]> {
  return await axios.get(`/api/v1/knowledge/space/department/all`, { params });
}

export async function batchCreateDepartmentKnowledgeSpacesApi(
  departmentIds: number[],
): Promise<DepartmentKnowledgeSpaceSummary[]> {
  return await axios.post(`/api/v1/knowledge/space/department/batch-create`, {
    items: departmentIds.map((department_id) => ({ department_id })),
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
