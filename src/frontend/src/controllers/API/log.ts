import axios from "../request";

export const paramsSerializer = (params) => {
    return Object.keys(params)
        .map(key => {
            const value = params[key];
            if (value === undefined) {
                return null; // 只返回非undefined的值
            }
            if (Array.isArray(value)) {
                return value.map(val => `${key}=${val}`).join('&');
            }
            return `${key}=${value}`;
        })
        .filter(item => item !== null) // 过滤掉值为null的项
        .join('&');
}

// 获取操作过组下资源的所有用户
export async function getOperatorsApi(): Promise<[]> {
    return await axios.get('/api/v1/audit/operators')
}

// 获取用户所管理的用户组内的应用
export async function getGroupsApi(params: { keyword, page, page_size }): Promise<[]> {
    return await axios.get('/api/v1/group/manage/resources', { params })
}

// 审计视角 获取用户所管理的用户组内的应用
export async function getAuditGroupsApi(params: { keyword, page, page_size }): Promise<[]> {
    return await axios.get('/api/v1/group/audit/resources', { params })
}

// 运营视角 获取用户所管理的用户组内的应用
export async function getOperationGroupsApi(params: { keyword, page, page_size }): Promise<[]> {
    return await axios.get('/api/v1/group/operation/resources', { params })
}

// 分页获取审计列表
export async function getLogsApi({ page, pageSize, userIds, groupId = '', start, end, moduleId = '', action = '' }: {
    page: number,
    pageSize: number,
    userIds?: number[],
    groupId?: string,
    start?: string,
    end?: string,
    moduleId?: string,
    action?: string
}): Promise<{ data: any[], total: number }> {
    const uids = userIds?.reduce((pre, val) => `${pre}&operator_ids=${val}`, '') || ''
    const startStr = start ? `&start_time=${start}` : ''
    const endStr = end ? `&end_time=${end}` : ''
    return await axios.get(
        `/api/v1/audit?page=${page}&limit=${pageSize}&group_ids=${groupId}${uids}` +
        `&system_id=${moduleId}&event_type=${action}` + startStr + endStr
    )
}

// 系统模块
export async function getModulesApi(): Promise<{ data: any[] }> {
    return {
        data: [{ name: 'log.chat', value: 'chat' }, { name: 'log.build', value: 'build' }, { name: 'log.knowledge', value: 'knowledge' }, { name: 'log.system', value: 'system' }]
    }
}

const actions = [
    { name: 'log.createChat', value: 'create_chat' },
    { name: 'log.deleteChat', value: 'delete_chat' },
    { name: 'log.createBuild', value: 'create_build' },
    { name: 'log.updateBuild', value: 'update_build' },
    { name: 'log.deleteBuild', value: 'delete_build' },
    { name: 'log.createKnowledge', value: 'create_knowledge' },
    { name: 'log.deleteKnowledge', value: 'delete_knowledge' },
    { name: 'log.uploadFile', value: 'upload_file' },
    { name: 'log.deleteFile', value: 'delete_file' },
    { name: 'log.updateUser', value: 'update_user' },
    { name: 'log.forbidUser', value: 'forbid_user' },
    { name: 'log.recoverUser', value: 'recover_user' },
    { name: 'log.createUserGroup', value: 'create_user_group' },
    { name: 'log.deleteUserGroup', value: 'delete_user_group' },
    { name: 'log.updateUserGroup', value: 'update_user_group' },
    { name: 'log.createRole', value: 'create_role' },
    { name: 'log.deleteRole', value: 'delete_role' },
    { name: 'log.updateRole', value: 'update_role' },
    { name: 'log.userLogin', value: 'user_login' }
];

// 全部操作行为
export async function getActionsApi() {
    return actions
}

// 系统模块下操作行为
export async function getActionsByModuleApi(moduleId) {
    switch (moduleId) {
        case 'chat': return actions.filter(a => a.value.includes('chat'))
        case 'build': return actions.filter(a => a.value.includes('build'))
        case 'knowledge': return actions.filter(a => a.value.includes('knowledge') || a.value.includes('file'))
        case 'system': return actions.filter(a => a.value.includes('user') || a.value.includes('role'))
    }
}

// 应用数据标记列表
export async function getChatLabelsApi(params) {
    const { page, pageSize, keyword } = params

    return await axios.get('/api/v1/chat/app/list', {
        params: {
            page_num: page,
            page_size: pageSize,
            keyword
        }
    })
}

// 标注任务列表
export async function getMarksApi({ status, pageSize, page }): Promise<{}> {
    return await axios.get('/api/v1/mark/list', {
        params: {
            page_num: page,
            page_size: pageSize,
            status
        }
    }).then(res => {
        res.data = res.list
        return res
    })
}

// 创建标注任务
export async function createMarkApi(data: { app_list: string[], user_list: string[] }) {
    return await axios.post('/api/v1/mark/create_task', data)
}

// 删除标注任务
export async function deleteMarkApi(task_id) {
    return await axios.delete('/api/v1/mark/del', { params: { task_id } })
}

// 标注会话列表
export async function getMarkChatsApi({ task_id, keyword, page, pageSize, mark_status, mark_user }) {
    return await axios.get('/api/v1/chat/app/list', {
        params: {
            task_id,
            keyword,
            mark_status,
            mark_user: mark_user?.join(','),
            page_num: page,
            page_size: pageSize
        }
    })
}

// 获取用户标注权限
export async function getMarkPermissionApi(): Promise<boolean> {
    return await axios.get('/api/v1/user/mark')
}

// 更新标注状态
export async function updateMarkStatusApi(data: { session_id: string, task_id: number, status: number }) {
    return await axios.post('/api/v1/mark/mark', data)
}

// 获取下一个标注会话
export async function getNextMarkChatApi({ action, chat_id, task_id }) {
    return await axios.get('/api/v1/mark/next', {
        params: {
            action,
            chat_id,
            task_id
        }
    })
}

// 获取会话标注状态
export async function getMarkStatusApi({ chat_id, task_id }) {
    return await axios.get('/api/v1/mark/get_status', {
        params: {
            chat_id,
            task_id
        }
    })
}

// 获取会话分析策略配置
export async function getChatAnalysisConfigApi(): Promise<any> {
    return await axios.get('/api/v1/audit/session/config').then(res => {
        const formData = {
            reviewEnabled: res.flag,          // Map flag to reviewEnabled
            reviewKeywords: res.prompt,      // Map prompt to reviewKeywords
            reviewFrequency: res.day_cron === 'day' ? 'daily' : 'weekly',  // Check if it's daily or weekly
            reviewTime: res.hour_cron,       // Map hour_cron to reviewTime
            reviewDay: '',                    // Default empty, to be set if frequency is weekly
        };

        // Set reviewDay only if the frequency is weekly
        if (formData.reviewFrequency === 'weekly') {
            formData.reviewDay = res.day_cron; // Map the backend day to reviewDay (e.g., 'mon', 'tues', etc.)
        }

        return formData;
    })
}

// 更新会话分析策略配置
export async function updateChatAnalysisConfigApi(formData: { reviewEnabled: boolean, reviewKeywords: string, reviewFrequency: string, reviewTime: string, reviewDay: string }) {
    const backendData = {
        flag: formData.reviewEnabled,         // Map reviewEnabled to flag
        prompt: formData.reviewKeywords,      // Map reviewKeywords to prompt
        day_cron: formData.reviewFrequency === 'daily' ? 'day' : formData.reviewDay,  // Convert frequency and day
        hour_cron: formData.reviewTime,      // Map reviewTime to hour_cron
    };

    return await axios.post('/api/v1/audit/session/config', backendData)
}

// 审计视角 获取会话的统计数据
export async function getAuditChatStatisticsApi(params: { flow_ids, group_ids, start_date, end_date, page, page_size, order_field, order_type }) {
    return await axios.get('/api/v1/audit/session/chart', {
        params,
        paramsSerializer
    })
}


// 审计视角 获取报告下载链接
export async function getAuditReportDownloadLinkApi(params: { flow_ids, group_ids, start_date, end_date }) {
    return await axios.get('/api/v1/audit/session/chart/export', { params, paramsSerializer })
}

// 运营视角 获取会话的统计数据
export async function getOperationChatStatisticsApi(params: { flow_ids, group_ids, start_date, end_date, page, page_size, order_field, order_type }) {
    return await axios.get('/api/v1/operation/session/chart', {
        params,
        paramsSerializer
    })
}

// 运营视角 获取报告下载链接
export async function getOperationReportDownloadLinkApi(params: { flow_ids, group_ids, start_date, end_date }) {
    return await axios.get('/api/v1/operation/session/chart/export', { params, paramsSerializer })
}


// 获取审计应用列表
export async function getAuditAppListApi(params: {
    flow_ids,
    user_ids,
    group_ids,
    start_date,
    end_date,
    feedback,
    review_status,
    page,
    page_size,
    keyword,
}) {
    return await axios.get('/api/v1/audit/session', {
        params, paramsSerializer
    })
}

//导出审计信息exportAduitDataApi
export async function exportAduitDataApi(params: {
    flow_ids,
    user_ids,
    group_ids,
    start_date,
    end_date,
    feedback,
    review_status,
    keyword,
}) {
    return await axios.get('/api/v1/audit/export', {
        params, paramsSerializer
    })
}

//导出运营信息exportAduitDataApi
export async function exportOperationDataApi(params: {
    flow_ids,
    user_ids,
    group_ids,
    start_date,
    end_date,
    feedback,
    keyword,
}) {
    return await axios.get('/api/v1/operation/export', {
        params, paramsSerializer
    })
}

// 手动审查应用使用情况
export async function auditApi(params: {
    flow_ids,
    user_ids,
    group_ids,
    start_date,
    end_date,
    feedback,
    review_status
}): Promise<[]> {
    return await axios.get('/api/v1/audit/session/review', { params, paramsSerializer })
}

// 获取运营应用列表
export async function getOperationAppListApi(params: {
    flow_ids,
    user_ids,
    group_ids,
    start_date,
    end_date,
    feedback,
    page,
    page_size,
    keyword,
}) {
    return await axios.get('/api/v1/operation/session', {
        params, paramsSerializer
    })
}