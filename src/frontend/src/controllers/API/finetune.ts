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
export const getPresetFileApi = async (): Promise<FileItem[]> => {
    return await (axios.get(`/api/v1/finetune/job/file/preset`) as Promise<FileDB[]>).then((data) => {
        return data.map(item => {
            return {
                id: item.id,
                checked: false,
                sampleSize: 1000,
                name: item.name,
                dataSource: item.url
            }
        }) as FileItem[]
    });
};

// 获取下载链接
export const getFileUrlApi = async (urlkey): Promise<{ url: string }> => {
    return await axios.get(`/api/v1/finetune/job/file/download?file_url=${urlkey}`);
};