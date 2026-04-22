import axios from "@/controllers/request"

export interface KnowledgeSpaceSummary {
  id: number
  name: string
  description?: string | null
  space_kind?: "normal" | "department"
  department_id?: number | null
  department_name?: string | null
}

export async function getManagedKnowledgeSpacesApi(params?: {
  order_by?: string
}): Promise<KnowledgeSpaceSummary[]> {
  return await axios.get(`/api/v1/knowledge/space/managed`, {
    params: {
      order_by: params?.order_by,
    },
  })
}

export async function batchCreateDepartmentKnowledgeSpacesApi(
  departmentIds: number[]
): Promise<KnowledgeSpaceSummary[]> {
  return await axios.post(`/api/v1/knowledge/space/department/batch-create`, {
    items: departmentIds.map((departmentId) => ({
      department_id: departmentId,
    })),
  })
}
