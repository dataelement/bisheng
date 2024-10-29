import axios from "../request";

/**
 * 获取工作流节点模板s
 */
export const getWorkflowNodeTemplate = async (): Promise<any[]> => {
    return await axios.get("/api/v1/workflow/template");
}