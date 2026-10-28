import axios from "@/controllers/request"

export interface InviteCodeItem {
  id: number
  code: string
  batch_name: string
  limit: number
  used: number
  bind_user: number
  bind_user_name: string | null
  create_time: string
}

export interface InviteCodePage {
  total: number
  items: InviteCodeItem[]
}

export interface InviteCodeQuery {
  page: number
  pageSize: number
  keyword: string
}

export async function listInviteCodesApi(query: InviteCodeQuery): Promise<InviteCodePage> {
  const keyword = encodeURIComponent(query.keyword)
  return await axios.get(`/api/v1/invite/codes?page=${query.page}&page_size=${query.pageSize}&keyword=${keyword}`)
}

export async function createInviteCodesApi(name: string, num: number, limit: number): Promise<{ codes: string[] }> {
  return await axios.post("/api/v1/invite/code", { name, num, limit })
}

export async function updateInviteCodeApi(id: number, name: string, limit: number): Promise<InviteCodeItem> {
  return await axios.put(`/api/v1/invite/code/${id}`, { name, limit })
}

export async function deleteInviteCodeApi(id: number): Promise<void> {
  await axios.delete(`/api/v1/invite/code/${id}`)
}
