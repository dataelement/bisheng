// @ts-strict-ignore
import { paramsSerializer } from ".";
import axios from "../request";
import type { AuditAppOption, AuditDeptCandidates, AuditRow, OrgSelection } from "@/types/api/audit";

export const EMPTY_ORG_SELECTION: OrgSelection = {
    deptIds: [],
    includeDescendants: true,
    includeNone: false,
    includeUnrecorded: false,
}

export const isOrgSelectionEmpty = (selection: OrgSelection): boolean =>
    !selection.deptIds.length && !selection.includeNone && !selection.includeUnrecorded

/**
 * Organisation params of the audit endpoints. An empty selection sends nothing,
 * so the request stays identical to the pre-F003 one. `/audit*` takes
 * `dept_ids` as a repeated key; runtime records take a comma string and
 * `"true"` / `"false"` flags (design §6.1).
 */
export const toDeptParams = (selection: OrgSelection | undefined, style: 'repeat' | 'csv' = 'repeat') => {
    if (!selection || isOrgSelectionEmpty(selection)) return {}
    const flag = (value: boolean) => (style === 'csv' ? String(value) : value)
    return {
        ...(selection.deptIds.length
            ? {
                dept_ids: style === 'csv' ? selection.deptIds.join(',') : selection.deptIds,
                include_descendants: flag(selection.includeDescendants),
            }
            : {}),
        ...(selection.includeNone ? { include_none: flag(true) } : {}),
        ...(selection.includeUnrecorded ? { include_unrecorded: flag(true) } : {}),
    }
}

// F003: organisation candidates inside the caller's audit scope.
export async function getAuditDepartmentsApi(params: {
    parentId?: number
    keyword?: string
    tenantId?: number | null
    limit?: number
}): Promise<AuditDeptCandidates> {
    return await axios.get('/api/v1/audit/departments', {
        params: {
            parent_id: params.parentId,
            keyword: params.keyword || undefined,
            tenant_id: params.tenantId ?? undefined,
            limit: params.limit ?? 100,
        },
    })
}

// Fetch users who operated on resources in the selected group.
export async function getOperatorsApi(): Promise<[]> {
    return await axios.get('/api/v1/audit/operators')
}

/**
 * Filters of the system-audit page. The list and the export take the same
 * set — F056 AC-32 says the export is "the query under a different pagination
 * driver", so there is one param builder and no second filter vocabulary.
 */
export interface AuditLogFilters {
    userIds?: number[]
    groupId?: string
    start?: string
    end?: string
    moduleId?: string
    action?: string
    /** F056 AC-28: only rows about this hosted application (deleted ones included). */
    targetAppId?: string
    /** F056 AC-30: global super narrowing to one tenant; anyone else may only name their own. */
    tenantId?: number | null
    /** F003: organisation the operator belonged to when the row was written. */
    org?: OrgSelection
}

// Empty strings / empty arrays are "no filter", not a filter for the empty
// value — dropping them keeps the query string readable and the export URL
// identical to the list's for the same selection.
const buildAuditParams = (filters: AuditLogFilters): Record<string, unknown> => {
    const raw: Record<string, unknown> = {
        group_ids: filters.groupId,
        operator_ids: filters.userIds,
        start_time: filters.start,
        end_time: filters.end,
        system_id: filters.moduleId,
        event_type: filters.action,
        target_app_id: filters.targetAppId,
        tenant_id: filters.tenantId,
        ...toDeptParams(filters.org),
    }
    return Object.fromEntries(
        Object.entries(raw).filter(([, value]) =>
            value !== undefined && value !== null && value !== '' && !(Array.isArray(value) && value.length === 0)),
    )
}

// 分页获取审计列表
export async function getLogsApi({ page, pageSize, ...filters }: AuditLogFilters & {
    page: number,
    pageSize: number,
}): Promise<{ data: AuditRow[], total: number }> {
    return await axios.get('/api/v1/audit', {
        params: { page, limit: pageSize, ...buildAuditParams(filters) },
        paramsSerializer,
    })
}

// F056 AC-32: every row the same filters would list, capped server-side;
// `total` is the uncapped count so the page can say the file is incomplete.
export async function exportSystemLogDataApi(filters: AuditLogFilters): Promise<{ data: AuditRow[], total: number }> {
    return await axios.get('/api/v1/audit/export/data', {
        params: buildAuditParams(filters),
        paramsSerializer,
    })
}

// F056 AC-28: options for the object-application selector — name / slug
// substring, deleted applications included so their events stay reachable.
export async function getAuditAppsApi(keyword: string, limit = 20): Promise<AuditAppOption[]> {
    return await axios.get('/api/v1/audit/apps', { params: { keyword, limit } })
}

/**
 * Deployment-shape switches the audit filter has to respect.
 *
 * `multi_tenant.enabled` defaults to false on a standard docker install, and
 * the flag only reaches the frontend through React context
 * (`appConfig.multiTenantEnabled`). This module must stay free of React, so
 * callers pass the flag down instead. Defaults keep the full list, so any
 * caller that does not care is unaffected.
 */
export type AuditFilterOptions = {
    multiTenantEnabled?: boolean
}

// Audit modules that only ever produce rows on a multi-tenant deployment.
const MULTI_TENANT_ONLY_MODULES = ['tenant']
// ...and the action prefixes behind them (`tenant.mount` / `unmount` /
// `disable` all describe attaching or detaching a CHILD tenant).
const MULTI_TENANT_ONLY_ACTION_PREFIXES = ['tenant.']

const filterMultiTenantOnly = <T extends { value: string }>(
    items: T[],
    multiTenantEnabled: boolean,
    pick: (item: T) => boolean,
): T[] => (multiTenantEnabled ? items : items.filter((item) => !pick(item)))

/**
 * Fold a structured v2 action into its `log.eventTypeEnum` key.
 *
 * This is the ONLY way a v2 action's i18n key may be produced. The audit table
 * derives it from the row (`systemLog/index.tsx` renderEventType), so a
 * hand-written key that folds differently gives you a correct filter dropdown
 * and a raw `open_api.api_key.issue` in the table cell — which is exactly how
 * the `openApiKeyIssue` / `openApiApiKeyIssue` split happened. Deriving both
 * sides from one function makes that divergence unrepresentable.
 */
export const actionToI18nKey = (action: string): string => {
    const [head, ...rest] = action.split(/[._]/).filter(Boolean)
    if (!head) return action
    return head + rest.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join('')
}

// 系统模块
// `tenant` / `llm` are synthetic v2 namespaces (action prefix `tenant.*` /
// `llm.server.*`). Backend `get_audit_logs` maps them to `action LIKE '...'`
// instead of `system_id = ?`. Keep this list in sync with backend
// `_V2_NAMESPACE_TO_ACTION_PREFIX` in audit_log.py.
//
// On a single-tenant deployment the 租户管理 module is a shell: there is no
// second tenant to mount, unmount or disable, so picking it can only ever
// return an empty result set.
export async function getModulesApi({ multiTenantEnabled = true }: AuditFilterOptions = {}): Promise<{ data: any[] }> {
    const modules = [
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
    ]
    return {
        data: filterMultiTenantOnly(
            modules,
            multiTenantEnabled,
            (module) => MULTI_TENANT_ONLY_MODULES.includes(module.value),
        ),
    }
}

// Legacy actions predate the structured `namespace.entity.verb` form: their
// i18n keys are irregular (`add_tool`, not `addTool`) and the audit table looks
// them up by the `event_type` column verbatim, so they stay hand-written.
const legacyActions = [
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
    { name: 'log.eventTypeEnum.update_sandbox_conf', value: 'update_sandbox_conf' },
    { name: 'log.eventTypeEnum.link_file_version', value: 'link_file_version' },
    { name: 'log.eventTypeEnum.set_primary_version', value: 'set_primary_version' },
    { name: 'log.eventTypeEnum.delete_file_version', value: 'delete_file_version' },
    { name: 'log.eventTypeEnum.dismiss_similar_file', value: 'dismiss_similar_file' },
];

/**
 * Module → legacy actions, written out instead of matched by substring: a
 * substring rule put `knowledge_space` actions under 知识库 and left the tool
 * and sandbox actions out of 系统. Must agree with the `system_id` each
 * backend writer records (api/services/audit_log.py).
 */
const LEGACY_MODULE_ACTIONS: Record<string, string[]> = {
    chat: ['create_chat', 'delete_chat'],
    build: ['create_build', 'update_build', 'delete_build'],
    knowledge: [
        'create_knowledge', 'delete_knowledge', 'upload_file', 'delete_file',
        'link_file_version', 'set_primary_version', 'delete_file_version', 'dismiss_similar_file',
    ],
    system: [
        'update_user', 'forbid_user', 'recover_user',
        'create_user_group', 'delete_user_group', 'update_user_group',
        'create_role', 'delete_role', 'update_role', 'user_login',
        'add_tool', 'update_tool', 'delete_tool', 'update_sandbox_conf',
    ],
    dashboard: ['create_dashboard', 'update_dashboard', 'delete_dashboard'],
    subscription: ['create_channel', 'delete_channel'],
    knowledge_space: ['create_knowledge_space', 'delete_knowledge_space'],
}

// Synthetic v2 modules own every structured action under their prefix.
const V2_MODULE_PREFIX: Record<string, string> = {
    tenant: 'tenant.',
    llm: 'llm.server.',
    approval: 'approval.',
    open_api: 'open_api.',
    app: 'app.',
}

/**
 * Structured v2 actions, in dropdown order.
 *
 * **This list is one half of a lockstep pair** — its twin is
 * `_UI_VISIBLE_V2_ACTIONS` in `bisheng/database/models/audit_log.py`. An action
 * registered on the backend only is written to the database and can never be
 * found on the audit page; registered here only, the filter returns nothing
 * forever. `src/test/logActions.test.ts` reads the Python tuple and asserts the
 * two are equal, so the pair cannot drift silently again.
 *
 * Only the on-wire value is written here. The label key is derived by
 * `actionToI18nKey`, which is also what the audit table uses — see the note on
 * that function for why hand-writing it is not an option.
 */
export const V2_ACTIONS: string[] = [
    'tenant.mount',
    'tenant.unmount',
    'tenant.disable',
    'llm.server.create',
    'llm.server.update',
    'llm.server.delete',
    'approval.request.submit',
    'approval.task.approve',
    'approval.task.reject',
    'approval.request.withdraw',
    'approval.route.pass',
    'approval.handler.success',
    'approval.handler.failed',
    'approval.exception.retry',
    'approval.exception.assign_approver',
    'approval.exception.cancel',
    'approval.flow.update',
    'approval.scenario.toggle',
    'approval.scenario.create',
    'approval.exception.skip_node',
    'approval.menu_access.revoke_grant',
    // F049 open API auth. The grant / share_link / ws families get their first
    // writers in later waves; registered in one go so the filter is touched
    // exactly once per feature.
    'open_api.service_account.create',
    'open_api.service_account.update',
    'open_api.service_account.enable',
    'open_api.service_account.disable',
    'open_api.service_account.delete',
    'open_api.api_key.issue',
    'open_api.api_key.update',
    'open_api.api_key.revoke',
    'open_api.api_key.revoke_all',
    'open_api.api_key.expire',
    'open_api.api_key.invalidate_by_subject',
    'open_api.grant.add',
    'open_api.grant.update',
    'open_api.grant.remove',
    'open_api.grant.remove_all',
    'open_api.share_link.revoke',
    'open_api.share_link.expire',
    'open_api.ws.connect',
    // F052 MCP face: one row per tools/call, plus door refusals.
    'open_api.mcp.tool_call',
    // F054 hosted applications — the state machine, meta updates and the
    // data-tab row edit / export.
    'app.publish',
    'app.publish_pending',
    'app.manual_publish',
    'app.stop',
    'app.resume',
    'app.delete',
    'app.delete_hook_failed',
    'app.meta_update',
    'app.data_row_edit',
    'app.data_export',
    'app.data_restore',
    // F056 governance.
    'app.visibility_change',
    // F055 resource-tier admin surface (system page "resource tiers" tab).
    'app.tier_update',
    // F055 publish pipeline. Its own family, deliberately NOT nested under
    // `app.publish` — that name is already the state action "the app went
    // online", and reusing the prefix makes both the filter and the namespace
    // mapping ambiguous.
    'app.release.submit',
    'app.release.precheck_failed',
    'app.release.scan_blocked',
    'app.release.version_created',
    'app.release.approval_created',
    'app.release.approval_exception',
    'app.release.self_approval',
    'app.release.approved',
    'app.release.rejected',
    'app.release.withdrawn',
    'app.release.cancelled',
    'app.release.online',
    'app.release.pending_online',
    'app.release.iteration_failed',
    'app.release.schema_migration_failed',
    'app.release.manual_publish',
    'app.release.capability_declared',
    'app.release.preview_started',
    'app.release.preview_reclaimed',
    'app.release.rollback',
    'app.secret.set',
    'app.secret.delete',
    'app.secret.rebuild',
];

const actions = [
    ...legacyActions,
    ...V2_ACTIONS.map(value => ({ name: `log.eventTypeEnum.${actionToI18nKey(value)}`, value })),
];

// 全部操作行为
export async function getActionsApi({ multiTenantEnabled = true }: AuditFilterOptions = {}) {
    return filterMultiTenantOnly(
        actions,
        multiTenantEnabled,
        (action) => MULTI_TENANT_ONLY_ACTION_PREFIXES.some((prefix) => action.value.startsWith(prefix)),
    )
}

// 系统模块下操作行为
export async function getActionsByModuleApi(moduleId: string) {
    const legacy = LEGACY_MODULE_ACTIONS[moduleId]
    if (legacy) return actions.filter(a => legacy.includes(a.value))
    const prefix = V2_MODULE_PREFIX[moduleId]
    return prefix ? actions.filter(a => a.value.startsWith(prefix)) : []
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


export type AuditUsageType = 'daily' | 'assistant' | 'workflow' | 'task'

/** F003 additions shared by the app-usage list and its export. */
type SessionAuditExtras = {
    org?: OrgSelection
    usage_type?: AuditUsageType
}

const withSessionExtras = <T extends SessionAuditExtras>({ org, usage_type, ...rest }: T) => ({
    ...rest,
    usage_type: usage_type || undefined,
    ...toDeptParams(org),
})

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
} & SessionAuditExtras) {
    return await axios.get('/api/v1/audit/session', {
        params: withSessionExtras(params), paramsSerializer
    })
}

// F003: user candidates of the app-usage tab, inside the caller's audit scope.
export async function getAuditSessionUsersApi(keyword = '', limit = 50): Promise<{ user_id: number, user_name: string }[]> {
    return await axios.get('/api/v1/audit/session/users', { params: { keyword: keyword || undefined, limit } })
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
} & SessionAuditExtras) {
    return await axios.get('/api/v1/audit/session/export/data', {
        params: withSessionExtras(params), paramsSerializer
    })
}
