import axios from "@/controllers/request"

export interface KnowledgeSpaceSummary {
  id: number
  name: string
  description?: string | null
  space_level?: "public" | "department" | "team" | "personal"
  space_kind?: "normal" | "department"
  department_id?: number | null
  department_name?: string | null
}

export interface KnowledgeSpaceOptionPage {
  data: KnowledgeSpaceSummary[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface KnowledgeSpaceChild {
  id: number
  name?: string
  file_name?: string
  type?: "folder" | "file"
  file_type?: number | string
  status?: number | string
  success_file_num?: number
  visible_success_file_num?: number
  file_num?: number
  processing_file_num?: number
}

export interface KnowledgeSpaceFolderStats {
  folder_id: number
  file_num: number
  success_file_num: number
  visible_success_file_num: number
  processing_file_num: number
}

export async function getAuthorizedKnowledgeSpaceOptionsApi(params?: {
  keyword?: string
  page?: number
  page_size?: number
  order_by?: string
}): Promise<KnowledgeSpaceOptionPage> {
  return await axios.get(`/api/v1/knowledge/space/options`, {
    params: {
      keyword: params?.keyword,
      page: params?.page,
      page_size: params?.page_size,
      order_by: params?.order_by,
    },
  })
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

export async function getKnowledgeSpaceChildrenApi(params: {
  space_id: number | string
  parent_id?: number | string | null
  page_size?: number
  cursor?: string | null
  order_field?: string
  order_sort?: string
}): Promise<{ data: KnowledgeSpaceChild[]; page_size: number; has_more: boolean; next_cursor: string | null }> {
  const { space_id, ...query } = params
  const response = await axios.get(`/api/v1/knowledge/space/${space_id}/children`, {
    params: {
      parent_id: query.parent_id || undefined,
      page_size: query.page_size,
      cursor: query.cursor || undefined,
      order_field: query.order_field,
      order_sort: query.order_sort,
    },
  })
  const payload: any = response || {}
  return {
    data: payload.data || [],
    page_size: payload.page_size || query.page_size || 50,
    has_more: Boolean(payload.has_more),
    next_cursor: payload.next_cursor || null,
  }
}

export async function getKnowledgeSpaceFolderStatsApi(params: {
  space_id: number | string
  folder_ids: Array<number | string>
}): Promise<KnowledgeSpaceFolderStats[]> {
  const folderIds = Array.from(new Set(params.folder_ids.map(Number).filter((id) => id > 0)))
  if (!folderIds.length) return []
  const response = await axios.post(`/api/v1/knowledge/space/${params.space_id}/folder-stats`, {
    folder_ids: folderIds,
  })
  const payload: any = response?.data || response || {}
  return payload.stats || []
}
