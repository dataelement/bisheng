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
export const createAssistantsApi = async (name, prompt, url) => {
    if (url) {
        // logo保存相对路径
        url = url.match(/(icon.*)\?/)?.[1]
    }
    return await axios.post(`/api/v1/assistant`, { name, prompt, logo: url })
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
    if (data.logo) {
        // logo保存相对路径
        data.logo = data.logo.match(/(icon.*)\?/)?.[1]
    }
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


// 获取工具集合
export const getAssistantToolsApi = async (type: 'all' | 'default' | 'custom'): Promise<any> => {
    const queryStr = {
        all: '',
        default: '?is_preset=true',
        custom: '?is_preset=false'
    }
    return await axios.get(`/api/v1/assistant/tool_list${queryStr[type]}`)
};

// 修改内置工具配置
export const updateAssistantToolApi = async (tool_id, extra) => {
    return await axios.post(`/api/v1/assistant/tool/config`, { tool_id, extra })
}