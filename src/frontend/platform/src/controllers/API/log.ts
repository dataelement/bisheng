// @ts-strict-ignore
import { paramsSerializer } from ".";
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
// `tenant` / `llm` are synthetic v2 namespaces (action prefix `tenant.*` /
// `llm.server.*`). Backend `get_audit_logs` maps them to `action LIKE '...'`
// instead of `system_id = ?`. Keep this list in sync with backend
// `_V2_NAMESPACE_TO_ACTION_PREFIX` in audit_log.py.
export async function getModulesApi(): Promise<{ data: any[] }> {
    return {
        data: [
            { name: 'log.systemIdEnum.chat', value: 'chat' },
            { name: 'log.systemIdEnum.build', value: 'build' },
            { name: 'log.systemIdEnum.knowledge', value: 'knowledge' },
            { name: 'log.systemIdEnum.system', value: 'system' },
            { name: 'log.systemIdEnum.dashboard', value: 'dashboard' },
            { name: 'log.systemIdEnum.subscribe', value: 'subscription' },
            { name: 'log.systemIdEnum.knowledgeSpace', value: 'knowledge_space' },
            { name: 'log.systemIdEnum.tenant', value: 'tenant' },
            { name: 'log.systemIdEnum.llm', value: 'llm' },
            { name: 'log.systemIdEnum.approval', value: 'approval' },
            { name: 'log.systemIdEnum.openApi', value: 'open_api' },
            { name: 'log.systemIdEnum.appFactory', value: 'app' },
        ],

    }
}

const actions = [
    { name: 'log.eventTypeEnum.createChat', value: 'create_chat' },
    { name: 'log.eventTypeEnum.deleteChat', value: 'delete_chat' },
    { name: 'log.eventTypeEnum.createBuild', value: 'create_build' },
    { name: 'log.eventTypeEnum.updateBuild', value: 'update_build' },
    { name: 'log.eventTypeEnum.deleteBuild', value: 'delete_build' },
    { name: 'log.eventTypeEnum.createKnowledge', value: 'create_knowledge' },
    { name: 'log.eventTypeEnum.deleteKnowledge', value: 'delete_knowledge' },
    { name: 'log.eventTypeEnum.uploadFile', value: 'upload_file' },
    { name: 'log.eventTypeEnum.deleteFile', value: 'delete_file' },
    { name: 'log.eventTypeEnum.updateUser', value: 'update_user' },
    { name: 'log.eventTypeEnum.forbidUser', value: 'forbid_user' },
    { name: 'log.eventTypeEnum.recoverUser', value: 'recover_user' },
    { name: 'log.eventTypeEnum.createUserGroup', value: 'create_user_group' },
    { name: 'log.eventTypeEnum.deleteUserGroup', value: 'delete_user_group' },
    { name: 'log.eventTypeEnum.updateUserGroup', value: 'update_user_group' },
    { name: 'log.eventTypeEnum.createRole', value: 'create_role' },
    { name: 'log.eventTypeEnum.deleteRole', value: 'delete_role' },
    { name: 'log.eventTypeEnum.updateRole', value: 'update_role' },
    { name: 'log.eventTypeEnum.userLogin', value: 'user_login' },
    { name: 'log.eventTypeEnum.add_tool', value: 'add_tool' },
    { name: 'log.eventTypeEnum.update_tool', value: 'update_tool' },
    { name: 'log.eventTypeEnum.delete_tool', value: 'delete_tool' },
    { name: 'log.eventTypeEnum.create_dashboard', value: 'create_dashboard' },
    { name: 'log.eventTypeEnum.update_dashboard', value: 'update_dashboard' },
    { name: 'log.eventTypeEnum.delete_dashboard', value: 'delete_dashboard' },
    { name: 'log.eventTypeEnum.create_channel', value: 'create_channel' },
    { name: 'log.eventTypeEnum.delete_channel', value: 'delete_channel' },
    { name: 'log.eventTypeEnum.create_knowledge_space', value: 'create_knowledge_space' },
    { name: 'log.eventTypeEnum.delete_knowledge_space', value: 'delete_knowledge_space' },
    // v2 structured actions surfaced to operators (2026-05-06 product call):
    // tenant lifecycle + LLM server lifecycle only. Keep in sync with backend
    // `_UI_VISIBLE_V2_ACTIONS`. Note: i18n keys use camelCase to avoid
    // colliding with i18next's `.` nesting separator (the on-wire `value`
    // keeps the dotted form expected by the audit_log.action column).
    { name: 'log.eventTypeEnum.tenantMount', value: 'tenant.mount' },
    { name: 'log.eventTypeEnum.tenantUnmount', value: 'tenant.unmount' },
    { name: 'log.eventTypeEnum.tenantDisable', value: 'tenant.disable' },
    { name: 'log.eventTypeEnum.llmServerCreate', value: 'llm.server.create' },
    { name: 'log.eventTypeEnum.llmServerUpdate', value: 'llm.server.update' },
    { name: 'log.eventTypeEnum.llmServerDelete', value: 'llm.server.delete' },
    { name: 'log.eventTypeEnum.approvalRequestSubmit', value: 'approval.request.submit' },
    { name: 'log.eventTypeEnum.approvalTaskApprove', value: 'approval.task.approve' },
    { name: 'log.eventTypeEnum.approvalTaskReject', value: 'approval.task.reject' },
    { name: 'log.eventTypeEnum.approvalRequestWithdraw', value: 'approval.request.withdraw' },
    { name: 'log.eventTypeEnum.approvalRoutePass', value: 'approval.route.pass' },
    { name: 'log.eventTypeEnum.approvalHandlerSuccess', value: 'approval.handler.success' },
    { name: 'log.eventTypeEnum.approvalHandlerFailed', value: 'approval.handler.failed' },
    { name: 'log.eventTypeEnum.approvalExceptionRetry', value: 'approval.exception.retry' },
    { name: 'log.eventTypeEnum.approvalExceptionAssignApprover', value: 'approval.exception.assign_approver' },
    { name: 'log.eventTypeEnum.approvalExceptionCancel', value: 'approval.exception.cancel' },
    { name: 'log.eventTypeEnum.approvalFlowUpdate', value: 'approval.flow.update' },
    { name: 'log.eventTypeEnum.approvalScenarioToggle', value: 'approval.scenario.toggle' },
    { name: 'log.eventTypeEnum.approvalScenarioCreate', value: 'approval.scenario.create' },
    { name: 'log.eventTypeEnum.approvalMenuAccessRevokeGrant', value: 'approval.menu_access.revoke_grant' },
    // F049 open API auth (design D11). Lockstep with backend
    // `_UI_VISIBLE_V2_ACTIONS` in database/models/audit_log.py and the
    // `log.eventTypeEnum` copy in bs.json (three languages). The grant /
    // share_link / ws families start producing events in later waves; they are
    // registered here in one go so the filter never has to be touched twice.
    { name: 'log.eventTypeEnum.openApiServiceAccountCreate', value: 'open_api.service_account.create' },
    { name: 'log.eventTypeEnum.openApiServiceAccountUpdate', value: 'open_api.service_account.update' },
    { name: 'log.eventTypeEnum.openApiServiceAccountEnable', value: 'open_api.service_account.enable' },
    { name: 'log.eventTypeEnum.openApiServiceAccountDisable', value: 'open_api.service_account.disable' },
    { name: 'log.eventTypeEnum.openApiServiceAccountDelete', value: 'open_api.service_account.delete' },
    { name: 'log.eventTypeEnum.openApiKeyIssue', value: 'open_api.api_key.issue' },
    { name: 'log.eventTypeEnum.openApiKeyUpdate', value: 'open_api.api_key.update' },
    { name: 'log.eventTypeEnum.openApiKeyRevoke', value: 'open_api.api_key.revoke' },
    { name: 'log.eventTypeEnum.openApiKeyRevokeAll', value: 'open_api.api_key.revoke_all' },
    { name: 'log.eventTypeEnum.openApiKeyExpire', value: 'open_api.api_key.expire' },
    { name: 'log.eventTypeEnum.openApiKeyInvalidateBySubject', value: 'open_api.api_key.invalidate_by_subject' },
    { name: 'log.eventTypeEnum.openApiGrantAdd', value: 'open_api.grant.add' },
    { name: 'log.eventTypeEnum.openApiGrantUpdate', value: 'open_api.grant.update' },
    { name: 'log.eventTypeEnum.openApiGrantRemove', value: 'open_api.grant.remove' },
    { name: 'log.eventTypeEnum.openApiGrantRemoveAll', value: 'open_api.grant.remove_all' },
    { name: 'log.eventTypeEnum.openApiShareLinkRevoke', value: 'open_api.share_link.revoke' },
    { name: 'log.eventTypeEnum.openApiShareLinkExpire', value: 'open_api.share_link.expire' },
    { name: 'log.eventTypeEnum.openApiWsConnect', value: 'open_api.ws.connect' },
    // F054 hosted applications. Lockstep with backend `_UI_VISIBLE_V2_ACTIONS`
    // (audit_log.py) and `AppAuditAction` — an action registered on one side
    // only is written to the DB and never appears in this filter.
    { name: 'log.eventTypeEnum.appPublish', value: 'app.publish' },
    { name: 'log.eventTypeEnum.appPublishPending', value: 'app.publish_pending' },
    { name: 'log.eventTypeEnum.appManualPublish', value: 'app.manual_publish' },
    { name: 'log.eventTypeEnum.appStop', value: 'app.stop' },
    { name: 'log.eventTypeEnum.appResume', value: 'app.resume' },
    { name: 'log.eventTypeEnum.appDelete', value: 'app.delete' },
    { name: 'log.eventTypeEnum.appDeleteHookFailed', value: 'app.delete_hook_failed' },
    { name: 'log.eventTypeEnum.appMetaUpdate', value: 'app.meta_update' },
    { name: 'log.eventTypeEnum.appDataRowEdit', value: 'app.data_row_edit' },
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
        case 'dashboard': return actions.filter(a => a.value.includes('dashboard'))
        case 'subscription': return actions.filter(a => a.value.includes('channel'))
        case 'knowledge_space': return actions.filter(a => a.value.includes('knowledge_space'))
        case 'tenant': return actions.filter(a => a.value.startsWith('tenant.'))
        case 'llm': return actions.filter(a => a.value.startsWith('llm.server.'))
        case 'approval': return actions.filter(a => a.value.startsWith('approval.'))
        case 'open_api': return actions.filter(a => a.value.startsWith('open_api.'))
        case 'app': return actions.filter(a => a.value.startsWith('app.'))
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
export async function createMarkApi(data: { app_list: string[], user_list: number[] }) {
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
/**
 * 获取应用分组列表
 * @param params 请求参数：keyword（关键词）、page（页码）、page_size（每页大小）
 * @param config axios 配置，包含 signal（用于取消请求）
 * @returns 返回分组列表数据
 */
export async function getGroupsApi(
    params: { keyword: string; page: number; page_size: number },
    config?: { signal?: AbortSignal } // 接收 AbortSignal
): Promise<any[]> {
    return await axios.get("/api/v1/group/manage/resources", {
        params, // 请求参数
        signal: config?.signal, // 绑定 AbortSignal
    });
}


// 获取审计应用列表
export async function getAuditAppListApi(params: {
    flow_ids,
    user_ids,
    group_ids,
    start_date,
    end_date,
    feedback,
    sensitive_status,
    page,
    page_size
}) {
    return await axios.get('/api/v1/audit/session', {
        params, paramsSerializer
    })
}

// 导出csv

export async function exportCsvApi(params: {
    flow_ids,
    user_ids,
    group_ids,
    start_date,
    end_date,
    feedback,
    sensitive_status
}) {
    return await axios.get('/api/v1/audit/session/export', {
        params, paramsSerializer
    })
}

// 包装csv的表格数据
export async function exportCsvDataApi(params: {
    flow_ids,
    user_ids,
    group_ids,
    start_date,
    end_date,
    feedback,
    sensitive_status
}) {
    return await axios.get('/api/v1/audit/session/export/data', {
        params, paramsSerializer
    })
}
