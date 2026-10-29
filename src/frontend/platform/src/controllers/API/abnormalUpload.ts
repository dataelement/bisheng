import axios from "../request"

export interface AbnormalUploadItem {
    file_id: number
    file_name: string
    knowledge_id: number
    knowledge_name: string
    space_level: string
    status: number
    uploader_name: string
    company_name: string
    department_name: string
    office_name: string
    remark: string
    update_time: string
}

export interface AbnormalUploadPage {
    data: AbnormalUploadItem[]
    total: number
}

export interface AbnormalUploadOrgOptions {
    companies: string[]
    departments: string[]
    offices: string[]
    knowledges: string[]
    uploaders: string[]
}

export interface AbnormalUploadQuery {
    page: number
    page_size?: number
    status?: number
    space_level?: string
    keyword?: string
    knowledge_name?: string
    uploader_name?: string
    uploader_company?: string
    uploader_department?: string
    uploader_office?: string
    update_time_from?: string
    update_time_to?: string
}

export function listAbnormalUploads(query: AbnormalUploadQuery): Promise<AbnormalUploadPage> {
    return axios.get("/api/v1/knowledge/space/abnormal-uploads", { params: query })
}

export function listAbnormalUploadOrgOptions(): Promise<AbnormalUploadOrgOptions> {
    return axios.get("/api/v1/knowledge/space/abnormal-uploads/org-options")
}

export function retryAbnormalUpload(fileId: number): Promise<{ file_id: number }> {
    return axios.post(`/api/v1/knowledge/space/abnormal-uploads/${fileId}/retry`, {})
}

export function deleteAbnormalUpload(fileId: number): Promise<{ file_id: number }> {
    return axios.post(`/api/v1/knowledge/space/abnormal-uploads/${fileId}/delete`, {})
}

export function retryAbnormalUploads(fileIds: number[]): Promise<{ retried: number; failed: number }> {
    return axios.post("/api/v1/knowledge/space/abnormal-uploads/retry-batch", { file_ids: fileIds })
}

export function deleteAbnormalUploads(fileIds: number[]): Promise<{ deleted: number; failed: number }> {
    return axios.post("/api/v1/knowledge/space/abnormal-uploads/delete-batch", { file_ids: fileIds })
}
