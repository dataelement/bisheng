import axios from "../request";

// 获取操作过组下资源的所有用户
export async function getOperatorsApi(): Promise<[]> {
    return await axios.get('/api/v1/audit/operators')
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
        data: [{ name: '会话', value: 'chat' }, { name: '构建', value: 'build' }, { name: '知识库', value: 'knowledge' }, { name: '系统', value: 'system' }]
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