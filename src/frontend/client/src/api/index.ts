import * as Types from '~/@types';
import request from "./request";

/**
 * 获取知识库构建状态
 */
export async function getKnowledgeStatusApi(): Promise<any> {
    return await request.get(`/api/v1/knowledge/status`)
}

/**
 * 语音转文字
 */
export async function getVoice2TextApi(data: any): Promise<any> {
    return await request.postMultiPart(`/api/v1/llm/workbench/asr`, data)
}

/**
 * 文字转语音
 */
export const textToSpeech = (text: string): Promise<{ audio: string }> => {
    const encodedText = encodeURIComponent(text);
    return request.get(`/api/v1/llm/workbench/tts?text=${encodedText}`);
};


/**
 * 获取工作台模型列表
 */
export async function getWorkbenchModelListApi(): Promise<Types.SelectModelResponse> {
    return await request.get(`/api/v1/llm/workbench`)
}

/**
 * 获取分享链接
 */
export async function getShareLinkApi(type: string, chatId: string, data: any): Promise<any> {
    return await request.post(`/api/v1/share-link/generate_share_link`, {
        resource_type: type,
        resource_id: chatId,
        meta_data: data
    })
}

/**
 * 解析分享链接的信息
 */
export async function getShareParamsApi(token: string): Promise<any> {
    return await request.get(`/api/v1/share-link/${token}`)
}
