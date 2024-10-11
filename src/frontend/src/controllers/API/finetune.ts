import { FileDB, FileItem, TaskDB } from "../../types/api/finetune";
import axios from "../request";

interface Tasks_query {
    /**
     * 每页条数
     */
    limit?: number;
    model_name: string;
    /**
     * 页码
     */
    page?: number;
    /**
     * 关联的RT服务ID
     */
    server?: string;
    /**
     * 训练任务的状态，1: 训练中 2: 训练失败 3: 任务中止 4: 训练成功 5: 发布完成
     */
    status?: string;
}
// 任务列表
export const getTasksApi = async (params: Tasks_query): Promise<TaskDB[]> => {
    const server = params.server === 'all' ? undefined : params.server;
    const status = params.status === 'all'
        ? undefined :
        params.status === '2'
            ? '2,3' :
            params.status === '4'
                ? '4,5' : params.status;
    return await axios.get(`/api/v1/finetune/job`, { params: { ...params, server, status } });
};

// 创建任务
export const createTaskApi = async (data: any): Promise<TaskDB> => {
    const filterData = (arr) => {
        return arr?.reduce((res, el) => {
            const item = {
                id: el.id,
                num: el.sampleSize,
                url: el.dataSource,
                name: el.name
            }
            return el.checked ? [...res, item] : res
        }, []) || []
    }
    const train_data = filterData(data.train_data)
    const preset_data = filterData(data.preset_data)
    return await axios.post(`/api/v1/finetune/job`, { ...data, train_data, preset_data });
};

// 删除任务
export const deleteTaskApi = async (taskId: string) => {
    return await axios.delete(`/api/v1/finetune/job?job_id=${taskId}`);
};

// 取消任务训练
export const cancelTaskApi = async (taskId: string): Promise<TaskDB> => {
    return await axios.post(`/api/v1/finetune/job/cancel?job_id=${taskId}`);
};

// 取消发布任务
export const unPublishTaskApi = async (taskId: string): Promise<TaskDB> => {
    return await axios.post(`/api/v1/finetune/job/publish/cancel?job_id=${taskId}`);
};

// 发布任务
export const publishTaskApi = async (taskId: string): Promise<TaskDB> => {
    return await axios.post(`/api/v1/finetune/job/publish?job_id=${taskId}`);
};

// 获取任务详情
export const getTaskInfoApi = async (taskId: string): Promise<{ finetune: TaskDB, log: any, report: any, loss_data: any }> => {
    return await axios.get(`/api/v1/finetune/job/info?job_id=${taskId}`);
};

// 修改任务名
export const updataTaskNameApi = async (taskId: string, name: string) => {
    return await axios.patch(`/api/v1/finetune/job/model`, {
        id: taskId,
        model_name: name
    });
};

// 上传文件
export const uploadTaskFileApi = async (data, config): Promise<FileItem> => {
    return await axios.post(`/api/v1/finetune/job/file`, data, config).then((res: any) => {
        if (!res.length) return null
        const { id, url, name } = res[0]
        return {
            id,
            name,
            checked: true,
            sampleSize: 1000,
            dataSource: url
        }
    });
};

// 获取预设文件列表
export const getPresetFileApi = async (data: { page_size: number, page_num: number, keyword: string }): Promise<FileItem[]> => {
    return await (axios.get(`/api/v1/finetune/job/file/preset`, { params: data }) as Promise<FileDB[]>).then((data) => {
        const list = data.list.map(item => {
            return {
                ...item,
                id: item.id,
                checked: false,
                sampleSize: 1000,
                name: item.name,
                dataSource: item.url
            }
        })
        return { data: list, total: data.total }
    });
};

// 获取下载链接
export const getFileUrlApi = async (urlkey): Promise<{ url: string }> => {
    return await axios.get(`/api/v1/finetune/job/file/download?file_url=${urlkey}`);
};

// 获模型列表
export const getModelListApi = async (): Promise<any> => {
    return await axios.get(`/api/v1/llm`);
}

// 添加模型
export const addLLmServer = async (data: any) => {
    return await axios.post(`/api/v1/llm`, data)
};

// 修改模型
export const updateLLmServer = async (data: any) => {
    return await axios.put(`/api/v1/llm`, data)
}

// 删除模型
export const deleteLLmServer = async (server_id: string) => {
    return await axios.delete(`/api/v1/llm`, { data: { server_id } })
}

// 模型上下线
export const changeLLmServerStatus = async (model_id: string, online: number) => {
    return await axios.post(`/api/v1/llm/online`, { model_id, online })
}

// 获取模型详情
export const getLLmServerDetail = async (server_id: string): Promise<any> => {
    return await axios.get(`/api/v1/llm/info?server_id=${server_id}`)
}

// 获取知识库模型配置
export const getKnowledgeModelConfig = async (): Promise<any> => {
    return await axios.get(`/api/v1/llm/knowledge`)
}

// 更新知识库模型配置
export const updateKnowledgeModelConfig = async (data: any): Promise<any> => {
    return await axios.post(`/api/v1/llm/knowledge`, data)
}

// 获取助手模型配置
export const getAssistantModelConfig = async (): Promise<any> => {
    return await axios.get(`/api/v1/llm/assistant`)
}

// 更新助手模型配置
export const updateAssistantModelConfig = async (data: any): Promise<any> => {
    return await axios.post(`/api/v1/llm/assistant`, data)
}

// 获取评测模型配置
export const getEvaluationModelConfig = async (): Promise<any> => {
    return await axios.get(`/api/v1/llm/evaluation`)
}

// 更新评测模型配置
export const updateEvaluationModelConfig = async (data: any): Promise<any> => {
    return await axios.post(`/api/v1/llm/evaluation`, data)
}

// 获取助手模型可选列表
export const getAssistantModelList = async (): Promise<any> => {
    return await axios.get(`/api/v1/llm/assistant/llm_list`)
}

// 创建数据集
export const createDatasetApi = async (data: { name: string, files: string, qa_list: string[] }): Promise<any> => {
    return await axios.post(`/api/v1/finetune/job/file/preset `, data);
}

// 删除数据集
export const deleteDatasetApi = async (id) => {
    return await axios.delete(`/api/v1/finetune/job/file/preset?file_id=${id}`);
}