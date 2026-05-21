import axios from "@/controllers/request"

export interface KnowledgeSpaceTagLibraryListItem {
  id: number
  name: string
  description?: string | null
  tag_count: number
  is_builtin: boolean
}

export interface KnowledgeSpaceTagLibraryDetail extends KnowledgeSpaceTagLibraryListItem {
  tags: string[]
}

export interface KnowledgeSpaceTagLibraryPage {
  data: KnowledgeSpaceTagLibraryListItem[]
  total: number
}

export async function getKnowledgeSpaceTagLibrariesApi(params?: {
  page?: number
  page_size?: number
  keyword?: string
}): Promise<KnowledgeSpaceTagLibraryPage> {
  return await axios.get("/api/v1/knowledge/space/tag-libraries", { params })
}

export async function getKnowledgeSpaceTagLibraryApi(id: number): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.get(`/api/v1/knowledge/space/tag-libraries/${id}`)
}

export async function createKnowledgeSpaceTagLibraryApi(data: {
  name: string
  description?: string
  tags: string[]
}): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.post("/api/v1/knowledge/space/tag-libraries", data)
}

export async function importKnowledgeSpaceTagLibraryTextApi(data: {
  name: string
  description?: string
  content: string
}): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.post("/api/v1/knowledge/space/tag-libraries/import/text", data)
}

export async function updateKnowledgeSpaceTagLibraryApi(
  id: number,
  data: {
    name?: string
    description?: string
    tags?: string[]
  },
): Promise<KnowledgeSpaceTagLibraryDetail> {
  return await axios.put(`/api/v1/knowledge/space/tag-libraries/${id}`, data)
}

export async function deleteKnowledgeSpaceTagLibraryApi(id: number): Promise<boolean> {
  return await axios.delete(`/api/v1/knowledge/space/tag-libraries/${id}`)
}
