import { ReactFlowJsonObject } from "@xyflow/react";
import { FlowStyleType, FlowType, FlowVersionItem } from "../../types/flow";
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
export function saveReportFormApi(vid, flowId, data: Variable[]) {
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
            version_id: vid,
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
export async function getFlowApi(flowId: string, version: string = 'v1'): Promise<FlowType> {
    return await axios.get(`/api/${version}/flows/${flowId}`)
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
export async function readFlowsFromDatabase(page: number = 1, pageSize: number = 20, search: string, tag_id = -1) {
    const tagIdStr = tag_id === -1 ? '' : `&tag_id=${tag_id}`
    const { data, total }: { data: any[], total: number } = await axios.get(`/api/v1/flows/?page_num=${page}&page_size=${pageSize}&name=${search}${tagIdStr}`);
    return { data, total };
}

/* app list */
export async function getAppsApi({ page = 1, pageSize = 20, keyword, tag_id = -1, type }) {
    const tagIdStr = tag_id === -1 ? '' : `&tag_id=${tag_id}`
    const map = { assistant: 5, skill: 1, flow: 10 }
    const flowType = map[type] ? `&flow_type=${map[type]}` : ''
    const { data, total }: { data: any[], total: number } = await axios.get(`/api/v1/workflow/list?page_num=${page}&page_size=${pageSize}&name=${keyword}${tagIdStr}${flowType}`);
    const newData = data.map(item => {
        if (item.flow_type !== 5) return item
        return {
            ...item,
            description: item.desc,
            version_list: item.version_list || [],
        }
    })
    return { data: newData, total };
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
    logo: string,
    name: string,
    description: string,
    guide_word: string
}, userName: string) => {
    if (params.logo) {
        // logo保存相对路径
        params.logo = params.logo.match(/(icon.*)\?/)?.[1]
    }
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
    if (updatedFlow.logo) {
        // logo保存相对路径
        updatedFlow.logo = updatedFlow.logo.match(/(icon.*)\?/)?.[1]
    }
    return await axios.patch(`/api/v1/flows/${updatedFlow.id}`, {
        logo: updatedFlow.logo || '',
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
export async function readOnlineFlows(page: number = 1, searchKey: string = "") {
    const data: { data: any, total: number } = await axios.get(`/api/v1/flows/?page_num=${page}&page_size=${100}&status=2&name=${searchKey}`);
    return data;
}


// 解析 custom 组件节点
export async function reloadCustom(code): Promise<any> {
    const response = await axios.post("/api/v1/component/custom_component", {
        code,
        "field": "",
        "frontend_node": {}
    });
    return response
}


/**
 * 获取技能对应的版本列表.
 *
 * @returns {Promise<any>}.
 * @throws .
 */
export async function getFlowVersions(flow_id): Promise<{ data: FlowVersionItem[], total: number }> {
    return await axios.get(`/api/v1/flows/versions`, {
        params: { flow_id }
    });
}

/**
 * 创建新的技能版本.
 *
 * @param {object} versionData - 新版本的数据.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function createFlowVersion(flow_id, versionData: { name: string, description: string, original_version_id: number, data: any }) {
    return await axios.post(`/api/v1/flows/versions?flow_id=${flow_id}`, versionData);
}

/**
 * 获取单个版本的信息.
 *
 * @param {string} versionId - 版本的ID.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function getVersionDetails(versionId: string) {
    return await axios.get(`/api/v1/flows/versions/${versionId}`);
}

/**
 * 更新版本信息.
 *
 * @param {string} versionId - 要更新的版本ID.
 * @param {object} versionData - 更新的版本数据.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function updateVersion(versionId: string, versionData: { name: string, description: string, data: any }) {
    return await axios.put(`/api/v1/flows/versions/${versionId}`, versionData);
}

/**
 * 删除版本.
 *
 * @param {string} versionId - 要删除的版本ID.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function deleteVersion(versionId: string) {
    return await axios.delete(`/api/v1/flows/versions/${versionId}`);
}

/**
 * 切换版本.
 *
 * @param {object} versionData - 包含要更改到的版本ID的数据.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function changeCurrentVersion({ flow_id, version_id }: { flow_id: string, version_id: number }) {
    return await axios.post(`/api/v1/flows/change_version?flow_id=${flow_id}&version_id=${version_id}`);
}

/**
 * 运行测试用例.
 */
export async function runTestCase(data: { question_list, version_list, node_id, inputs }): Promise<any[]> {
    return await axios.post(`/api/v1/flows/compare`, data);
}