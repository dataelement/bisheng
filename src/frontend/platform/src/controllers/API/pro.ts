import axios from "../request";

/**
 * 保存敏感词
 */
export const sensitiveSaveApi = async (data: any): Promise<any> => {
    const { id, type, isCheck, words, wordsType, autoReply } = data

    return await axios.post(`/api/sensitive/saveWords`, {
        resource_id: id,
        resource_type: type,
        is_check: isCheck,
        words,
        words_type: wordsType,
        auto_reply: autoReply
    });
};

/**
 * 获取敏感词配置
 */
export const getSensitiveApi = async (resourceId, resourceType): Promise<any> => {

    return await axios.get(`/api/sensitive/wordsDetail`, {
        params: {
            resourceId,
            resourceType
        }
    });
};

/**
 * Department traffic control APIs
 */
export const getDepartmentLimitDetailApi = async (deptId: number): Promise<any> => {
    return await axios.get(`/api/department-limit/detail/${deptId}`);
};

export const getDepartmentFlowsApi = async (
    page: number, pageSize: number, resourceType: string | number,
    departmentId: number, name: string
): Promise<any> => {
    if (!departmentId) return Promise.resolve([{ data: [], total: 0 }]);
    return await axios.get(`/api/department-limit/resources`, {
        params: { name, page, pageSize, resourceType, departmentId }
    });
};

export const saveDepartmentLimitApi = async (data: {
    departmentId: number;
    deptLimit: number;
    assistant: any[];
    skill: any[];
    workFlows: any[];
}): Promise<any> => {
    return await axios.post(`/api/department-limit/save`, {
        department_id: data.departmentId,
        dept_limit: data.deptLimit,
        assistant: data.assistant,
        skill: data.skill,
        work_flows: data.workFlows
    });
};

// GET sso URL (silent: suppress global error toast when service is unavailable)
export function getSSOurlApi() {
    return axios.get(`/api/oauth2/list`, { silent: true } as any)
}

export async function getKeyApi() {
    return await axios.get('/api/getkey')
}

export async function ldapLoginApi(username:string, password:string) {
    return await axios.post('/api/oauth2/ldap', {
        username,
        password
    })
}