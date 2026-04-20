import { AssistantDetail } from '@/types/assistant';
import axios from "../request";

export interface AssistantItemDB {
    create_time: string;
    desc: string;
    id: string;
    logo?: string;
    name: string;
    update_time: string;
    user_id: number;
    user_name: string;
    status: number;
}
// 获取助手列表
export const getAssistantsApi = async (page, limit, name, tag_id): Promise<AssistantItemDB[]> => {
    return await axios.get(`/api/v1/assistant`, {
        params: {
            page, limit, name,
            tag_id: tag_id === -1 ? null : tag_id
        }
    });
};

// 创建助手
export const createAssistantsApi = async (
    name: string,
    prompt: string,
    url: string,
    shareToChildren?: boolean,
) => {
    if (url) {
        // logo保存相对路径
        url = url.replace('/bisheng', '')
    }
    // F017: forward share_to_children only when the caller set it. Omit
    // the field when undefined so the backend applies the Root default
    // (`share_default_to_children`) rather than a forced boolean.
    const body: Record<string, any> = { name, prompt, logo: url }
    if (shareToChildren !== undefined) body.share_to_children = shareToChildren
    return await axios.post(`/api/v1/assistant`, body)
};

// 获取助手详情
export const getAssistantDetailApi = async (id, version): Promise<AssistantDetail> => {
    return await axios.get(`/api/${version}/assistant/info/${id}`)
};

// 获取助手系统模型
export const getAssistantModelsApi = async (): Promise<any> => {
    return await axios.get(`/api/v1/assistant/models`)
};

// 上下线助手
export const changeAssistantStatusApi = async (id, status) => {
    return await axios.post(`/api/v1/assistant/status`, { id, status })
};

// 保存助手
export const saveAssistanttApi = async (
    data: Omit<AssistantDetail, 'flow_list' | 'tool_list' | 'knowledge_list'> & { flow_list: string[], tool_list: number[], knowledge_list: number[] }
): Promise<any> => {
    return await axios.put(`/api/v1/assistant`, data)
};

// 删除助手
export const deleteAssistantApi = async (id) => {
    return await axios.post(`/api/v1/assistant/delete?assistant_id=${id}`)
};


// 获取会话选择列表
export const getChatOnlineApi = async (page, keyword, tag_id) => {
    return await axios.get(`/api/v1/chat/online`, {
        params: {
            page, keyword,
            limit: 40,
            tag_id: tag_id === -1 ? null : tag_id
        }
    })
}
// export const getChatOnlineApi = async (tag_id:-1) => {
//     const tagStr = tag_id === -1 ? '' : `tag_id=${tag_id}`
//     return await axios.get(`/api/v1/chat/online?${tagStr}`)
// };

// 刷新mcp服务
export const refreshMcpApi = async (): Promise<any> => {
    return await axios.post(`/api/v1/tool/mcp/refresh`)
}

// 获取自动优化任务taskid
export const getAssistantOptimizeTaskApi = async (assistant_id, prompt) => {
    return await axios.post(`/api/v1/assistant/auto/task`, { assistant_id, prompt })
}