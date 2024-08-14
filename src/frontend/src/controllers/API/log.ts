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
    { name: '新建会话', value: 'create_chat' }, { name: '删除会话', value: 'delete_chat' }, { name: '新建应用', value: 'create_build' }, { name: '编辑应用', value: 'update_build' },
    { name: '删除应用', value: 'delete_build' }, { name: '新建知识库', value: 'create_knowledge' }, { name: '删除知识库', value: 'delete_knowledge' }, { name: '知识库上传文件', value: 'upload_file' },
    { name: '知识库删除文件', value: 'delete_file' }, { name: '用户编辑', value: 'update_user' }, { name: '停用用户', value: 'forbid_user' }, { name: '启用用户', value: 'recover_user' },
    { name: '新建用户组', value: 'create_user_group' }, { name: '删除用户组', value: 'delete_user_group' }, { name: '编辑用户组', value: 'update_user_group' }, { name: '新建角色', value: 'create_role' },
    { name: '删除角色', value: 'delete_role' }, { name: '编辑角色', value: 'update_role' }, { name: '用户登录', value: 'user_login' }
]

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