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

export interface DepartmentKnowledgeSpaceApprovalSettings {
  approval_enabled: boolean;
  sensitive_check_enabled: boolean;
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

export async function getDepartmentKnowledgeSpaceApprovalSettingsApi(): Promise<DepartmentKnowledgeSpaceApprovalSettings> {
  return await axios.get(`/api/v1/approval/department-knowledge-space/settings`);
}

export async function updateDepartmentKnowledgeSpaceApprovalSettingsApi(
  data: DepartmentKnowledgeSpaceApprovalSettings,
): Promise<DepartmentKnowledgeSpaceApprovalSettings> {
  return await axios.put(`/api/v1/approval/department-knowledge-space/settings`, data);
}
