import { ReactFlowJsonObject } from "@xyflow/react";
import { FlowStyleType, FlowType, FlowVersionItem } from "../../types/flow";
import axios from "../request";


export type Evaluation = {
    file_path: string,
    file_name: string,
    unique_id: string,
    prompt: string,
    result_score: {
        answer_f1: string,
        answer_precision: string,
        answer_recall: string,
    },
    create_time: string,
    id: number,
    user_id: number,
    exec_type: string,
    version: number,
    status: number,
    progress?: string,
    result_file_path: string,
    is_delete: number,
    update_time: string,
    unique_name: string,
    version_name: string,
    user_name: string,
}

/**
 * 获取评测列表
 * @param data 
 * @returns 
 */
export const getEvaluationApi = async (page, limit): Promise<Evaluation[]> => {
    return await axios.get(`/api/v1/evaluation`, {
        params: {
            page, limit
        }
    });
};

/**
 * 创建测评任务
 */
export const createEvaluationApi = async (data): Promise<any> => {
    return await axios.post(`/api/v1/evaluation`, data,{
        headers: {
            'Content-Type':'multipart/form-data'
        }
    });
};

/**
 * 删除测评任务
 */
export const deleteEvaluationApi = async (id): Promise<any> => {
    return await axios.delete(`/api/v1/evaluation/${id}`);
};

/**
 * 获取下载链接
 */
export const getEvaluationUrlApi = async (id): Promise<{ url: string }> => {
    return await axios.get(`/api/v1/evaluation/result/file/download?file_url=${id}`);
};
