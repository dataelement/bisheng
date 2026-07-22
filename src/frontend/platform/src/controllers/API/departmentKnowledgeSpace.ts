import axios from "../request";

export interface DepartmentKnowledgeSpaceSummary {
  id: number;
  name: string;
  department_id?: number | null;
  department_name?: string | null;
  space_kind?: "normal" | "department";
  auth_type?: string;
  is_released?: boolean;
}

export interface RebindDepartmentKnowledgeSpaceRequest {
  department_id: number;
}

export async function getDepartmentKnowledgeSpacesApi(params?: {
  order_by?: "name" | "update_time";
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

export async function rebindDepartmentKnowledgeSpaceApi(
  spaceId: number,
  data: RebindDepartmentKnowledgeSpaceRequest,
): Promise<DepartmentKnowledgeSpaceSummary> {
  return await axios.put(`/api/v1/knowledge/space/department-binding/${spaceId}`, data);
}
