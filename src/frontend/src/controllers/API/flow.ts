import axios from ".";


/**
 * 保存组件 variables 变量
 */
export function saveVariableApi(data) {
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
    return axios.get(`/api/v1/variable/list`, { params }).then(res => {
        return res.data.map((item) => {
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
export function getReportFormApi(flow_id) {
    return axios.get(`/api/v1/report/report_temp`, {
        params: { flow_id }
    })
}

