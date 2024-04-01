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
}
// 获取助手列表
export const getAssistantsApi = async (page, limit, name): Promise<AssistantItemDB[]> => {
    return await axios.get(`/api/v1/assistant`, {
        params: {
            page, limit, name
        }
    });
};

// 创建助手
export const createAssistantsApi = async (name, prompt) => {
    return await axios.post(`/api/v1/assistant`, { name, prompt, logo: '' })
};

// 获取助手详情
export const getAssistantDetailApi = async (id): Promise<AssistantDetail> => {
    return await axios.get(`/api/v1/assistant/info/${id}`)
};

// 获取助手系统模型
export const getAssistantModelsApi = async (): Promise<any> => {
    return await axios.get(`/api/v1/assistant/models`)
};

// 自动优化
export const autoByPromptApi = async (id, prompt): Promise<any> => {
    return await axios.post(`/api/v1/assistant/auto`, { assistant_id: id, prompt })
};

// 保存助手
export const saveAssistanttApi = async (data: Omit<AssistantDetail, 'flow_list' | 'tool_list'> & { flow_list: string[], tool_list: number[] }): Promise<any> => {
    return await axios.put(`/api/v1/assistant`, data)
};



// 获取工具集合
export const getAssistantToolsApi = async (): Promise<any> => {
    return await axios.get(`/api/v1/assistant/tool_list`)
};
