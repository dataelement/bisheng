import axios from "@/controllers/request";

export interface OrganizationDepartmentResult {
  id: number;
  dept_id: string;
  name: string;
  status: string;
  parent_path: string;
}

export interface OrganizationMemberResult {
  user_id: number;
  user_name: string;
  person_id: string | null;
  enabled: boolean;
  is_primary: boolean;
  department: {
    id: number;
    dept_id: string;
    name: string;
    status: string;
    path: string;
  };
}

export interface MemberLocation {
  page: number;
  is_primary_filter: number | null;
  filter_adjusted: boolean;
}

export async function searchOrganizationApi<T>(
  params: {
    keyword: string;
    kind: "members" | "departments";
    page: number;
    include_archived: boolean;
    preferred_department_id?: number;
  },
  signal: AbortSignal
): Promise<{ data: T[]; total: number }> {
  return await axios.get("/api/v1/departments/search/directory", {
    params: { ...params, limit: 20 },
    signal,
  });
}

export async function locateOrganizationMemberApi(
  deptId: string,
  userId: number,
  isPrimary: string,
  includeArchived: boolean
): Promise<MemberLocation> {
  return await axios.get(
    `/api/v1/departments/${encodeURIComponent(deptId)}/members/locate`,
    {
      params: {
        user_id: userId,
        limit: 20,
        include_archived: includeArchived,
        is_primary: isPrimary === "all" ? undefined : Number(isPrimary),
      },
    }
  );
}
