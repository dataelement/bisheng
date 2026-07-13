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
    // return Promise.resolve({ data: '测试语音转文字内容' })
}

/**
 * 文字转语音
 *
 * skip403Redirect opts out of the global 403 redirect AND routes a non-200
 * business error (e.g. TTS synthesis failure, code 10026) through the
 * interceptor's translate-and-toast path instead of surfacing as a silent
 * malformed success — see request.ts's skip403Redirect branch.
 */
export const textToSpeech = (text: string): Promise<{ audio: string }> => {
    // const encodedText = encodeURIComponent(text);
    return request.post(`/api/v1/llm/workbench/tts`, { text }, { skip403Redirect: true } as any);
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
