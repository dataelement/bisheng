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

/**
 * F041: list the knowledge spaces selectable by the config author.
 * Matches the client daily-mode 口径 = "我创建的 + 我加入的 + 部门知识空间" (dedup union
 * of /mine + /joined + /department), NOT including the knowledge square. Loaded in one
 * shot with client-side name filtering (these endpoints are INV-6 exceptions, full-return).
 */
export async function getSelectableKnowledgeSpacesApi(): Promise<KnowledgeSpaceSummary[]> {
  const results = await Promise.all([
    axios.get(`/api/v1/knowledge/space/mine`).catch(() => []),
    axios.get(`/api/v1/knowledge/space/joined`).catch(() => []),
    axios.get(`/api/v1/knowledge/space/department`).catch(() => []),
  ])
  const byId = new Map<number, KnowledgeSpaceSummary>()
  results.flat().forEach((space: KnowledgeSpaceSummary) => {
    if (space && space.id != null && !byId.has(space.id)) {
      byId.set(space.id, space)
    }
  })
  return Array.from(byId.values())
}
