// @ts-strict-ignore
import { Button, Select } from '@bisheng/ui';
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";

import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { getActionsApi, getActionsByModuleApi, getLogsApi, getModulesApi, getOperatorsApi } from "@/controllers/API/log";
import { getUserGroupsApi } from "@/controllers/API/user";
import { useTable } from "@/util/hook";
import { formatDate } from "@/util/utils";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { LoadingIcon } from "@/components/bs-icons/loading";

const useGroups = () => {
    const [groups, setGroups] = useState([])
    const loadData = () => {
        getUserGroupsApi().then((res: any) => setGroups(res))
    }
    return { groups, loadData }
}
const useModules = () => {
    const [modules, setModules] = useState([])
    const loadModules = () => {
        getModulesApi().then(res => setModules(res.data))
    }
    return { modules, loadModules }
}

// v2.5.1 audit_log rows from `ainsert_v2()` only fill `action` / `target_type`
// / `target_id` and leave the legacy `system_id` / `event_type` / `object_type`
// columns NULL. Fall back to the structured fields so the page does not render
// the literal i18n key (`log.systemIdEnum.null`). Backend `_UI_VISIBLE_V2_ACTIONS`
// already restricts which v2 rows reach the list — these helpers only need to
// handle that whitelist plus a defensive fallback for unexpected rows.

// Backend audit notes use this literal marker; it is stored data, not UI copy.
// eslint-disable-next-line no-restricted-syntax
const editMarker = '编辑后';

// Structured action (`tenant.mount`, `approval.exception.assign_approver`) →
// camelCase i18n leaf key (`tenantMount`, `approvalExceptionAssignApprover`).
// Both `.` and `_` act as word separators: i18next treats `.` as a nesting
// separator and locale keys use camelCase throughout, so snake_case segments
// must also be folded into the camelCase form to resolve.
export const actionToI18nKey = (action: string): string => {
    const [head, ...rest] = action.split(/[._]/).filter(Boolean)
    if (!head) return action
    return head + rest.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join('')
}

const renderSystemId = (log: any, t: (key: string, opts?: any) => string): string => {
    if (log.system_id) return t(`log.systemIdEnum.${log.system_id}`)
    if (log.action) {
        const ns = String(log.action).split('.')[0]
        return t(`log.systemIdEnum.${ns}`, { defaultValue: ns })
    }
    return '-'
}

const renderEventType = (log: any, t: (key: string, opts?: any) => string): string => {
    if (log.event_type) return t(`log.eventTypeEnum.${log.event_type}`)
    if (log.action) {
        const key = actionToI18nKey(log.action)
        return t(`log.eventTypeEnum.${key}`, { defaultValue: log.action })
    }
    return '-'
}

const renderObjectType = (log: any, t: (key: string, opts?: any) => string): string => {
    if (log.object_type) return t(`log.objectTypeEnum.${log.object_type}`)
    if (log.target_type) return t(`log.objectTypeEnum.${log.target_type}`, { defaultValue: log.target_type })
    return t('log.objectTypeEnum.none')
}

const renderObjectName = (log: any, t: (key: string, opts?: any) => string): string => {
    return log.object_name || log.target_id || t('log.objectTypeEnum.none')
}

export default function SystemLog() {
    const { t } = useTranslation()
    const selectLabels = useSelectLabels()
    const { users, loadUsers } = useUsers()
    const { groups, loadData } = useGroups()
    const { modules, loadModules } = useModules()
    const { page, pageSize, loading, data: logs, total, setPage, filterData } = useTable({ pageSize: 20 }, (param) =>
        getLogsApi({ ...param })
    )
    const init = {
        userIds: [],
        groupId: '',
        start: undefined,
        end: undefined,
        moduleId: '',
        action: ''
    }

    const [actions, setActions] = useState<any[]>([])
    const [keys, setKeys] = useState({ ...init })

    const handleActionOpen = async () => {
        setActions((keys.moduleId ? await getActionsByModuleApi(keys.moduleId) : await getActionsApi()))
    }
    const handleSearch = () => {
        const startTime = keys.start && formatDate(keys.start, 'yyyy-MM-dd HH:mm:ss')
        const endTime = keys.end && formatDate(keys.end, 'yyyy-MM-dd HH:mm:ss').replace('00:00:00', '23:59:59')
        filterData({ ...keys, start: startTime, end: endTime })
    }
    const handleReset = () => {
        setKeys({ ...init })
        filterData(init)
    }
    useEffect(() => {
        loadUsers()
    }, [])

    return <div className="relative">
        {loading && (
            <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>
        )}
        <div className="h-[calc(100vh-128px-var(--license-banner-h,0px))] overflow-y-auto px-2 py-4 pb-10">
            <div className="flex flex-wrap gap-4">
                <Select
                    {...selectLabels}
                    multiple
                    showSearch
                    allowClear
                    className="w-[200px]"
                    aria-label={t('log.selectUser')}
                    placeholder={t('log.selectUser')}
                    options={users.filter(u => u.value != null && u.value !== '')}
                    value={keys.userIds}
                    onChange={(values) => setKeys({ ...keys, userIds: values })}
                />
                <Select
                    {...selectLabels}
                    allowClear
                    className="w-[200px]"
                    aria-label={t('log.selectUserGroup')}
                    placeholder={t('log.selectUserGroup')}
                    onOpenChange={(open) => { if (open) loadData() }}
                    value={keys.groupId || null}
                    onChange={(value) => setKeys({ ...keys, groupId: value == null ? '' : value })}
                    options={groups.filter(g => g.id != null && g.id !== '').map(g => ({ value: g.id, label: g.group_name }))}
                />
                <div className="w-[180px] relative">
                    <DatePicker value={keys.start} placeholder={t('log.startDate')} onChange={(t) => setKeys({ ...keys, start: t })} />
                </div>
                <div className="w-[180px] relative">
                    <DatePicker value={keys.end} placeholder={t('log.endDate')} onChange={(t) => setKeys({ ...keys, end: t })} />
                </div>
                <Select
                    {...selectLabels}
                    allowClear
                    className="w-[180px]"
                    aria-label={t('log.systemModule')}
                    placeholder={t('log.systemModule')}
                    onOpenChange={(open) => { if (open) loadModules() }}
                    value={keys.moduleId || null}
                    onChange={(value) => setKeys({ ...keys, action: '', moduleId: value == null ? '' : value })}
                    options={modules.filter(m => m.value != null && m.value !== '').map(m => ({ value: m.value, label: t(m.name) }))}
                />
                <Select
                    {...selectLabels}
                    allowClear
                    className="w-[180px]"
                    aria-label={t('log.actionBehavior')}
                    placeholder={t('log.actionBehavior')}
                    onOpenChange={(open) => { if (open) handleActionOpen() }}
                    value={keys.action || null}
                    onChange={(value) => setKeys({ ...keys, action: value == null ? '' : value })}
                    options={actions.filter(a => a.value != null && a.value !== '').map(a => ({ value: a.value, label: t(a.name) }))}
                />
                <div>
                    <Button className="mr-3" onClick={handleSearch}>
                        {t('log.searchButton')}
                    </Button>
                    <Button variant="outlined" onClick={handleReset} color="default">
                        {t('log.resetButton')}
                    </Button>
                </div>
            </div>
            <Table className="mb-[50px]">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('log.auditId')}</TableHead>
                        <TableHead className="w-[200px] min-w-[100px]">{t('log.username')}</TableHead>
                        <TableHead className="w-[200px] min-w-[100px]">{t('log.operationTime')}</TableHead>
                        <TableHead className="w-[100px] min-w-[100px]">{t('log.systemModule')}</TableHead>
                        <TableHead className="w-[150px] min-w-[100px]">{t('log.operationAction')}</TableHead>
                        <TableHead className="w-[150px] min-w-[100px]">{t('log.objectType')}</TableHead>
                        <TableHead className="w-[200px] min-w-[100px]">{t('log.operationObject')}</TableHead>
                        <TableHead className="w-[150px]">{t('log.ipAddress')}</TableHead>
                        <TableHead className="w-[250px] min-w-[250px]">{t('log.remark')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {logs.map((log: any) => (
                        <TableRow key={log.id}>
                            <TableCell>{log.id}</TableCell>
                            <TableCell><div className="max-w-[200px] break-all truncate-multiline">{log.operator_name}</div></TableCell>
                            <TableCell>{log.create_time.replace('T', ' ')}</TableCell>
                            <TableCell>{renderSystemId(log, t)}</TableCell>
                            <TableCell>{renderEventType(log, t)}</TableCell>
                            <TableCell>{renderObjectType(log, t)}</TableCell>
                            <TableCell><div className="max-w-[200px] break-all truncate-multiline">{renderObjectName(log, t)}</div></TableCell>
                            <TableCell>{log.ip_address}</TableCell>
                            <TableCell className="max-w-[250px]">
                                <div className="whitespace-pre-line break-all">{log.note?.replace(editMarker, `\n${editMarker}`) || t('log.objectTypeEnum.none')}</div>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
                {!logs.length && <TableFooter>
                    <TableRow>
                        <TableCell colSpan={9} className="text-center text-gray-400">{t('build.empty')}</TableCell>
                    </TableRow>
                </TableFooter>}
            </Table>
            {!logs.length && <div className="h-[700px]"></div>}
        </div>
        {/* Pagination */}
        {/* <Pagination count={10}></Pagination> */}
        <div className="bisheng-table-footer px-6 bg-background-login">
            <div className="flex items-center gap-2">
                <p className="desc">{t('log.auditManagement')}</p>
            </div>
            <AutoPagination
                className="float-right justify-end w-full mr-6"
                page={page}
                pageSize={pageSize}
                total={total}
                showTotal={true}
                onChange={(newPage) => setPage(newPage)}
            />
        </div>
    </div>
};


const useUsers = () => {
    const [users, setUsers] = useState<any[]>([]);
    const userRef = useRef([])
    const selectedRef = useRef([])

    const loadUsers = () => {
        getOperatorsApi().then(res => {
            const options = res.map((u: any) => ({ label: u.user_name, value: u.user_id }))
            userRef.current = options
            setUsers(options)
        })
    }
    const search = (name) => {
        // const newUsers = userRef.current.filter(u => u.label.toLowerCase().includes(name.toLowerCase())
        //     || selectedRef.current.includes(u.value))
        // setUsers(newUsers)
    }

    return {
        users,
        selectedRef,
        loadUsers,
        searchUser(name) {
            search(name)
        }
    }
}