import request from "./request";

/**
 * 获取知识库构建状态
 */
export async function getKnowledgeStatusApi(): Promise<any> {
    return await request.get(`/api/v1/knowledge/status`)
}