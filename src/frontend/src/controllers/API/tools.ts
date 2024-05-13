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

/**
 * 创建工具接口
 * POST请求
 * @returns Promise<any> 创建工具的结果
 */
export const createTool = async (data: any): Promise<any> => {
    return await axios.post(`/api/v1/assistant/tool_list`, data);
};

/**
 * 修改工具接口
 * PUT请求
 * @param toolId string 工具的ID
 * @returns Promise<any> 修改工具的结果
 */
export const updateTool = async (data: any): Promise<any> => {
    return await axios.put(`/api/v1/assistant/tool_list`, data);
};

/**
 * 删除工具接口
 * DELETE请求
 * @returns Promise<any> 删除工具的结果
 */
export const deleteTool = async (id: number): Promise<any> => {
    return await axios({
        method: 'delete',
        url: '/api/v1/assistant/tool_list',
        data: {
            tool_type_id: id
        }
    })
};

/**
 * 下载或解析tool schema的内容接口
 * POST请求
 * download_url string 
 * file_content string
 * @returns Promise<any> 下载或解析tool schema的结果
 */
export const downloadToolSchema = async (data: { download_url: string } | { file_content: string }): Promise<any> => {
    return await axios.post(`/api/v1/assistant/tool_schema`, data);
};

/**
 * 工具测试接口
 * @returns 
 */
export const testToolApi = async (data: {
    server_host: string
    extra: string
    auth_method: number
    auth_type: string
    api_key: string
    request_params: Object
}): Promise<any> => {
    return await axios({
        method: 'post',
        url: '/api/v1/assistant/tool_test',
        data
    })
};