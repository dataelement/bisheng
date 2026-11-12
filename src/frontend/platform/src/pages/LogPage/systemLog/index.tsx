// @ts-strict-ignore
import { Pagination, Button, DatePicker, Input, Select } from '@bisheng/ui';
import type { DatePickerError, DatePickerOpenRange } from '@bisheng/ui';
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";

import { useDatePickerLocale } from "@/hooks/useDatePickerLocale";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { notification } from "@bisheng/ui";
import {
    actionToI18nKey,
    AuditLogFilters,
    EMPTY_ORG_SELECTION,
    exportSystemLogDataApi,
    getActionsApi,
    getActionsByModuleApi,
    getAuditAppsApi,
    getLogsApi,
    getModulesApi,
    getOperatorsApi,
} from "@/controllers/API/log";
import { getTenantsApi } from "@/controllers/API/tenant";
import { getUserGroupsApi } from "@/controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useAdminScope } from "@/hooks/useAdminScope";
import { useTable } from "@/util/hook";
import { exportCsv, formatDate } from "@/util/utils";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import {
    buildAuditCsv,
    renderEventType,
    renderObjectName,
    renderObjectType,
    renderOperator,
    renderOrg,
    renderSystemId,
    toAppOptions,
} from "./auditRow";
import { AuditEmptyState } from "../components/AuditEmptyState";
import { OrgFilter } from "../components/OrgFilter";
import type { OrgSelection } from "@/types/api/audit";

const useGroups = () => {
    const [groups, setGroups] = useState([])
    const loadData = () => {
        getUserGroupsApi().then((res: any) => setGroups(res))
    }
    return { groups, loadData }
}
// `multiTenantEnabled` is threaded in from `appConfig` because the audit
// filter must not offer the 租户管理 module on a single-tenant deployment —
// it can never match a row there. See `getModulesApi` in controllers/API/log.
const useModules = (multiTenantEnabled: boolean) => {
    const [modules, setModules] = useState([])
    const loadModules = () => {
        getModulesApi({ multiTenantEnabled }).then(res => setModules(res.data))
    }
    return { modules, loadModules }
}

// F056 AC-28: object-application selector. Options come from the backend
// search (name / slug substring, deleted applications included) rather than a
// preloaded list — a tenant can hold far more applications than a dropdown
// should carry, and the deleted ones would otherwise never be offered.
const useAuditApps = (t: (key: string, opts?: any) => string) => {
    const [apps, setApps] = useState<{ label: string, value: string }[]>([])
    const search = (keyword: string) => {
        getAuditAppsApi(keyword).then(res => setApps(toAppOptions(res || [], t)))
    }
    return { apps, searchApps: search, loadApps: () => search('') }
}

// F056 AC-30: tenant filter for the global super on a multi-tenant
// deployment. Hidden while an F019 admin scope is set — the backend then
// pins every read to that tenant and a different `tenant_id` is rejected.
const useTenantFilter = (enabled: boolean) => {
    const { scope } = useAdminScope({ enabled })
    const [tenants, setTenants] = useState<{ id: number, tenant_name: string }[]>([])
    const loadTenants = () => {
        getTenantsApi({ page: 1, page_size: 100 }).then(res => setTenants(res?.data || []))
    }
    return { showTenant: enabled && scope.scope_tenant_id == null, tenants, loadTenants }
}

// Re-exported so this page stays the discoverable home of the audit-table
// rendering rules. The implementation lives next to the action list it has to
// agree with (controllers/API/log.ts) — keeping them in one file is what makes
// the filter label and the table cell provably the same key. The cell
// renderers themselves live in ./auditRow so the CSV export shares them.
// Backend audit data marker.
// eslint-disable-next-line no-restricted-syntax
const editMarker = '编辑后';
export { actionToI18nKey }

type FilterKeys = {
    userIds: number[]
    groupId: string
    dateRange: DatePickerOpenRange | null
    moduleId: string
    action: string
    targetAppId: string
    tenantId: string
    org: OrgSelection
    note: string
}

const init: FilterKeys = {
    userIds: [],
    groupId: '',
    dateRange: null,
    moduleId: '',
    action: '',
    targetAppId: '',
    tenantId: '',
    org: EMPTY_ORG_SELECTION,
    note: '',
}

// What the backend receives for one set of controls — the list and the
// export both go through here so they can never disagree (AC-32).
const toFilters = (keys: FilterKeys): AuditLogFilters => ({
    userIds: keys.userIds,
    groupId: keys.groupId,
    start: keys.dateRange?.[0] ? `${keys.dateRange[0]} 00:00:00` : undefined,
    end: keys.dateRange?.[1] ? `${keys.dateRange[1]} 23:59:59` : undefined,
    moduleId: keys.moduleId,
    action: keys.action,
    targetAppId: keys.targetAppId,
    tenantId: keys.tenantId ? Number(keys.tenantId) : undefined,
    org: keys.org,
    note: keys.note.trim(),
})

export default function SystemLog() {
    const { t } = useTranslation()
    const paginationLocale = usePaginationLocale();
    const datePickerLocale = useDatePickerLocale();
    const { appConfig } = useContext(locationContext)
    const { user } = useContext(userContext)
    const multiTenantEnabled = !!appConfig.multiTenantEnabled
    const selectLabels = useSelectLabels()
    const { users, loadUsers } = useUsers()
    const { groups, loadData } = useGroups()
    const { modules, loadModules } = useModules(multiTenantEnabled)
    const { apps, searchApps, loadApps } = useAuditApps(t)
    const { showTenant, tenants, loadTenants } = useTenantFilter(multiTenantEnabled && Boolean(user?.is_global_super))
    const { page, pageSize, loading, loaded, data: logs, total, setPage, filterData } = useTable({ pageSize: 20 }, (param) =>
        getLogsApi({ ...param })
    )

    const [actions, setActions] = useState<any[]>([])
    const [keys, setKeys] = useState<FilterKeys>({ ...init })
    const [dateError, setDateError] = useState<DatePickerError | null>(null)
    const [datePickerVersion, setDatePickerVersion] = useState(0)
    // The filters the table currently shows — the export follows these, not
    // the controls, so a half-edited form cannot export something the user
    // has not looked at.
    const appliedRef = useRef<AuditLogFilters>(toFilters(init))
    const [exporting, setExporting] = useState(false)

    const handleActionOpen = async () => {
        setActions((keys.moduleId ? await getActionsByModuleApi(keys.moduleId) : await getActionsApi({ multiTenantEnabled })))
    }
    const handleSearch = () => {
        const filters = toFilters(keys)
        appliedRef.current = filters
        filterData(filters)
    }
    const handleReset = () => {
        setKeys({ ...init })
        setDateError(null)
        setDatePickerVersion(version => version + 1)
        appliedRef.current = toFilters(init)
        filterData(toFilters(init))
    }
    const handleExport = () => {
        setExporting(true)
        captureAndAlertRequestErrorHoc(exportSystemLogDataApi(appliedRef.current)).then(res => {
            if (!res) return
            const rows = res.data || []
            if (!rows.length) {
                notification.open({ type: 'warning', description: t('log.exportEmpty') })
                return
            }
            if (res.total > rows.length) {
                notification.open({ type: 'warning', description: t('log.exportTruncated', { total: res.total, max: rows.length }) })
            }
            const csv = buildAuditCsv(rows, t, actionToI18nKey, { withTenant: showTenant })
            exportCsv(csv, `Audit_${formatDate(new Date(), 'yyyy-MM-dd_HH-mm-ss')}.csv`, true)
        }).finally(() => setExporting(false))
    }
    useEffect(() => {
        loadUsers()
    }, [])

    return <div className="relative flex min-h-0 flex-1 flex-col">
        {loading && (
            <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>
        )}
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 py-4 pb-20">
            <div className="flex shrink-0 flex-wrap gap-4">
                <OrgFilter value={keys.org} tenantId={keys.tenantId ? Number(keys.tenantId) : null}
                    onChange={org => setKeys({ ...keys, org })} />
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
                <DatePicker
                    key={datePickerVersion}
                    aria-label={t('datePicker.dateRange')}
                    className="w-[336px] max-w-full"
                    mode="range"
                    allowOpenRange
                    allowClear
                    value={keys.dateRange}
                    onChange={(dateRange: DatePickerOpenRange | null) => setKeys(current => ({ ...current, dateRange }))}
                    onValidationChange={setDateError}
                    locale={datePickerLocale}
                />
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
                <Select {...selectLabels} allowClear showSearch className="w-[220px]"
                    aria-label={t('log.selectApp')} placeholder={t('log.selectApp')}
                    options={apps} value={keys.targetAppId || null}
                    onOpenChange={open => { if (open) loadApps() }} onSearch={searchApps}
                    onChange={value => setKeys({ ...keys, targetAppId: value == null ? '' : String(value) })} />
                {showTenant && <Select {...selectLabels} allowClear className="w-[180px]"
                    aria-label={t('log.selectTenant')} placeholder={t('log.selectTenant')}
                    options={tenants.filter(tenant => tenant.id != null).map(tenant => ({ value: String(tenant.id), label: tenant.tenant_name }))}
                    value={keys.tenantId || null} onOpenChange={open => { if (open) loadTenants() }}
                    onChange={value => setKeys({ ...keys, tenantId: value == null ? '' : String(value) })} />}
                <Input
                    className="w-[200px]"
                    aria-label={t('log.remark')}
                    placeholder={t('log.remark')}
                    value={keys.note}
                    onChange={(event) => setKeys({ ...keys, note: event.target.value.slice(0, 200) })}
                />
                <div className="ml-auto mr-4 flex shrink-0 items-center gap-4">
                    <Button size="medium" onClick={handleSearch} disabled={Boolean(dateError)}>
                        {t('log.searchButton')}
                    </Button>
                    <Button size="medium" variant="outlined" onClick={handleReset} color="default">
                        {t('log.resetButton')}
                    </Button>
                    <Button size="medium" variant="outlined" color="default" loading={exporting} disabled={exporting} onClick={handleExport}>
                        {t('log.exportButton')}
                    </Button>
                </div>
            </div>
            <Table className="mb-[50px]" containerClassName="shrink-0">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('log.auditId')}</TableHead>
                        <TableHead className="w-[200px] min-w-[100px]">{t('log.username')}</TableHead>
                        <TableHead className="w-[200px] min-w-[120px]">{t('log.org.column')}</TableHead>
                        <TableHead className="w-[200px] min-w-[100px]">{t('log.operationTime')}</TableHead>
                        <TableHead className="w-[100px] min-w-[100px]">{t('log.systemModule')}</TableHead>
                        <TableHead className="w-[150px] min-w-[100px]">{t('log.operationAction')}</TableHead>
                        <TableHead className="w-[150px] min-w-[100px]">{t('log.objectType')}</TableHead>
                        <TableHead className="w-[200px] min-w-[100px]">{t('log.operationObject')}</TableHead>
                        {showTenant && <TableHead className="w-[120px] min-w-[100px]">{t('log.tenant')}</TableHead>}
                        <TableHead className="w-[150px]">{t('log.ipAddress')}</TableHead>
                        <TableHead className="w-[250px] min-w-[250px]">{t('log.remark')}</TableHead>
                        <TableHead className="w-[200px] min-w-[150px]">{t('log.reason')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {logs.map((log: any) => {
                        const operator = renderOperator(log, t)
                        return (
                            <TableRow key={log.id}>
                                <TableCell>{log.id}</TableCell>
                                <TableCell>
                                    <div className="max-w-[200px] break-all truncate-multiline">{operator.primary}</div>
                                    {operator.secondary && <div className="max-w-[200px] break-all text-xs text-muted-foreground">{operator.secondary}</div>}
                                </TableCell>
                                <TableCell><div className="max-w-[200px] break-all truncate-multiline">{renderOrg(log, t)}</div></TableCell>
                                <TableCell>{log.create_time.replace('T', ' ')}</TableCell>
                                <TableCell>{renderSystemId(log, t)}</TableCell>
                                <TableCell>{renderEventType(log, t, actionToI18nKey)}</TableCell>
                                <TableCell>{renderObjectType(log, t)}</TableCell>
                                <TableCell><div className="max-w-[200px] break-all truncate-multiline">{renderObjectName(log, t)}</div></TableCell>
                                {showTenant && <TableCell>{log.tenant_name || log.tenant_id || '-'}</TableCell>}
                                <TableCell>{log.ip_address}</TableCell>
                                <TableCell className="max-w-[250px]">
                                    <div className="whitespace-pre-line break-all">{log.note?.replace(editMarker, `\n${editMarker}`) || t('log.objectTypeEnum.none')}</div>
                                </TableCell>
                                <TableCell className="max-w-[200px]">
                                    <div className="break-all truncate-multiline">{log.reason || '-'}</div>
                                </TableCell>
                            </TableRow>
                        )
                    })}
                </TableBody>
            </Table>
            {loaded && !loading && logs.length === 0 && <AuditEmptyState />}
        </div>
        {/* Pagination */}

        <div className="bisheng-table-footer gap-4 px-6 bg-background-login">
            <Pagination locale={paginationLocale}
                className="ml-auto min-w-0"
                current={page}
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
    const search = () => {
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
