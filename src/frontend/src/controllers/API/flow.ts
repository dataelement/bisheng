import { ReactFlowJsonObject } from "reactflow";
import { FlowStyleType, FlowType } from "../../types/flow";
import axios from "../request";

/**
 * 保存组件 variables 变量
 */
export function saveVariableApi(data): Promise<{ id: string }> {
    return axios.post(`/api/v1/variable/`, data);
}

export const enum VariableType {
    /** 文本 */
    Text = "text",
    /** 下拉框 */
    Select = "select",
    /** 文件 */
    File = "file"
}
export interface Variable {
    id: string | number;
    update: boolean;
    name: string;
    maxLength: number;
    type: VariableType;
    nodeId: string;
    required: boolean;
    options: {
        key: string;
        value: string;
    }[];
    value?: string;
}
/**
 * get组件 variables 变量
 * params flow_id, node_id
 */
export function getVariablesApi(params) {
    return (axios.get(`/api/v1/variable/list`, { params }) as Promise<any[]>).then(res => {
        return res.map((item) => {
            const types = ['', VariableType.Text, VariableType.Select, VariableType.File]
            return {
                id: item.id,
                update: true,
                name: item.variable_name,
                type: types[item.value_type],
                nodeId: item.node_id,
                required: item.is_option === 1,
                maxLength: item.value_type === 1 ? item.value : '',
                options: item.value_type === 2 ? item.value
                    .split(',')
                    .map((op, i) => ({ key: i, value: op })) : [],
                value: ''
            }
        }) as Variable[]
    });
}

/**
 * 删除 变量
 */
export function delVariableApi(id) {
    return axios.delete(`/api/v1/variable/del`, {
        params: { id }
    });
}

/**
 * 保存变量和filenodename必填和排序信息
 */
export function saveReportFormApi(flowId, data: Variable[]) {
    const _data = data.map((item) => {
        const { id, maxLength, name: variable_name, nodeId: node_id, options, required, type } = item
        const types = {
            [VariableType.Text]: () => ({ type: 1, value: maxLength }),
            [VariableType.Select]: () => ({ type: 2, value: options.map((op) => op.value).join(',') }),
            [VariableType.File]: () => ({ type: 3, value: "0" }),
        }
        const typeInfo = types[type]()
        return {
            id,
            flow_id: flowId,
            node_id,
            is_option: Number(required),
            variable_name,
            value_type: typeInfo.type,
            value: typeInfo.value
        }
    })
    return axios.post(`/api/v1/variable/save_all`, _data);
}

/**
 * 初始化 file key 与 flowId的关系
 */
// export function initFileKeyApi(flow_id, key) {
//     return axios.post(`/api/v1/report/save_template`, { key, flow_id });
// }

/**
 * 获取 report表单信息
 */
export function getReportFormApi(flow_id): Promise<any> {
    return axios.get(`/api/v1/report/report_temp`, {
        params: { flow_id }
    })
}

/**
 * Fetches a flow from the database by ID.
 *
 * @param {number} flowId - The ID of the flow to fetch.
 * @returns {Promise<any>} The flow data.
 * @throws Will throw an error if fetching fails.
 */
export async function getFlowApi(flowId: string): Promise<FlowType> {
    return axios.get(`/api/v1/flows/${flowId}`)
}

/**
 * Saves a new flow to the database.
 *
 * @param {FlowType} newFlow - The flow data to save.
 * @returns {Promise<any>} The saved flow data.
 * @throws Will throw an error if saving fails.
 */
export async function saveFlowToDatabase(newFlow: {
    name: string;
    id: string;
    data: ReactFlowJsonObject;
    description: string;
    style?: FlowStyleType;
}): Promise<FlowType> {
    const id = newFlow.id ? { flow_id: newFlow.id } : {}
    const response: FlowType = await axios.post("/api/v1/flows/", {
        ...id,
        name: newFlow.name,
        data: newFlow.data,
        description: newFlow.description,
    });
    return response
}

/**
* Reads all flows from the database.
*
* @returns {Promise<any>} The flows data.
* @throws Will throw an error if reading fails.
*/
export async function readFlowsFromDatabase(page: number = 1, search: string) {
    const { data, total }: { data: any[], total: number } = await axios.get(`/api/v1/flows/?page_num=${page}&page_size=${20}&name=${search}`);
    return { data, pages: Math.ceil(total / 20) };
}

/**
 * Deletes a flow from the database.
 *
 * @param {string} flowId - The ID of the flow to delete.
 * @returns {Promise<any>} The deleted flow data.
 * @throws Will throw an error if deletion fails.
 */
export async function deleteFlowFromDatabase(flowId: string) {
    return await axios.delete(`/api/v1/flows/${flowId}`);
}

/**
 * 创建自定义技能
 * @param 技能名称 技能描述
 * @param 创建人
 */
export const createCustomFlowApi = async (params: {
    name: string,
    description: string,
    guide_word: string
}, userName: string) => {
    const response: FlowType = await axios.post("/api/v1/flows/", {
        ...params,
        data: null
    });

    return {
        ...response,
        write: true,
        status: 1,
        user_name: userName
    }
};

/**
 * 修改技能数据.
 *
 * @param {FlowType} updatedFlow - The updated flow data.
 * @returns {Promise<any>} The updated flow data.
 * @throws Will throw an error if the update fails.
 */
export async function updateFlowApi(
    updatedFlow: FlowType
): Promise<FlowType> {
    return axios.patch(`/api/v1/flows/${updatedFlow.id}`, {
        name: updatedFlow.name,
        data: updatedFlow.data,
        description: updatedFlow.description,
        guide_word: updatedFlow.guide_word
    });
}

/**
 * 上下线
 *
 */
export async function updataOnlineState(id, updatedFlow, open) {
    return await axios.patch(`/api/v1/flows/${id}`, {
        name: updatedFlow.name,
        description: updatedFlow.description,
        status: open ? 2 : 1
    });
}

/**
 * 获取在线技能列表.
 *
 * @returns {Promise<any>}.
 * @throws .
 */
export async function readOnlineFlows(page: number = 1) {
    const { data, total }: { data: any, total: number } = await axios.get(`/api/v1/flows/?page_num=${page}&page_size=${100}&status=2`);
    return data;
}
