import { WorkFlow } from "@/types/flow";
import axios from "../request";

/**
 * 获取工作流节点模板s
 */
export const getWorkflowNodeTemplate = async (): Promise<any[]> => {
    return await axios.get("/api/v1/workflow/template");
    // return new Promise(res => setTimeout(() => {
    //     res(template.data)
    // }, 100));
}

/**
 * 获取某工作流报告模板信息
 */
export const getWorkflowReportTemplate = async (key: string): Promise<any> => {
    return await axios.get(`/api/v1/workflow/report/file?version_key=${key}`);
}

/**
 * 创建工作流
 */
export const createWorkflowApi = async (name, desc, url): Promise<any> => {
    if (url) {
        // logo保存相对路径
        url = url.match(/(icon.*)\?/)?.[1]
    }
    return await axios.post("/api/v1/workflow/create", {
        name,
        description: desc,
        logo: url
    });
}

/**
 * 保存工作流
 */
export const saveWorkflow = async (versionId: number, data: WorkFlow): Promise<any> => {
    if (data.logo) {
        // logo保存相对路径
        data.logo = data.logo.match(/(icon.*)\?/)?.[1]
    }
    return await axios.put(`/api/v1/workflow/versions/${versionId}`, data);
}

/** 上线工作流 & 修改信息 
 * status: 2 上线 1 下线
*/
export const onlineWorkflow = async (flow, status = ''): Promise<any> => {
    const { name, description, logo} = flow
    const data = { name, description, logo: logo && logo.match(/(icon.*)\?/)?.[1] }
    if (status) {
        data['status'] = status
    }
    return await axios.patch(`/api/v1/workflow/update/${flow.id}`, data);
}