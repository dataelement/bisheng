import axios from "../request";

export interface KnowledgeTagItem {
    id: number;
    name: string;
    business_type?: string;
    business_id?: string;
    user_id?: number;
    create_time?: string;
    update_time?: string;
}

export interface KnowledgeTagListResponse {
    data: KnowledgeTagItem[];
    total: number;
}

/**
 * 获取知识库下的所有标签
 */
export async function getKnowledgeTagsApi(
    knowledge_id: number,
    params?: { keyword?: string; page?: number; limit?: number }
): Promise<KnowledgeTagListResponse> {
    return await axios.get(`/api/v1/knowledge/${knowledge_id}/tags`, { params });
}

/**
 * 创建新标签
 */
export async function createKnowledgeTagApi(
    knowledge_id: number,
    tag_name: string
): Promise<KnowledgeTagItem> {
    return await axios.post(`/api/v1/knowledge/tags`, {
        knowledge_id,
        tag_name
    });
}

/**
 * 修改标签名称
 */
export async function updateKnowledgeTagApi(
    knowledge_id: number,
    tag_id: number,
    tag_name: string
): Promise<KnowledgeTagItem> {
    return await axios.put(`/api/v1/knowledge/tags/${tag_id}`, {
        knowledge_id,
        tag_name
    });
}

/**
 * 删除指定的标签
 */
export async function deleteKnowledgeTagApi(knowledge_id: number, tag_id: number) {
    return await axios.delete(`/api/v1/knowledge/tags/${tag_id}`, {
        data: { knowledge_id }
    });
}

/**
 * 单个文件设置标签关系（全量替换）
 */
export async function setFileTagsApi(data: { knowledge_id: number; file_id: number; tag_ids: number[] }) {
    return await axios.post(`/api/v1/knowledge/file/tags`, data);
}

/**
 * 多文件批量追加标签
 */
export async function batchAddFileTagsApi(data: { knowledge_id: number; file_ids: number[]; tag_ids: number[] }) {
    return await axios.post(`/api/v1/knowledge/file/tags/batch`, data);
}
