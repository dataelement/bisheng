import { useContext, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { format, subDays } from 'date-fns'
import { useTranslation } from 'react-i18next'
import { Button, DatePicker, Pagination, Select } from '@bisheng/ui'
import type { DatePickerError, DatePickerOpenRange, DatePickerRange } from '@bisheng/ui'
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table'
import { locationContext } from '@/contexts/locationContext'
import { userContext } from '@/contexts/userContext'
import { useAdminScope } from '@/hooks/useAdminScope'
import { useDatePickerLocale } from '@/hooks/useDatePickerLocale'
import { usePaginationLocale } from '@/hooks/usePaginationLocale'
import { showApiError } from '@/controllers/request'
import { getTenantsApi } from '@/controllers/API/tenant'
import { cancelRuntimeAuditExport, createRuntimeAuditExport, downloadRuntimeAuditExport, getRuntimeAuditCandidates, withRuntimeOrg } from '@/controllers/API/runtimeAudit'
import { EMPTY_ORG_SELECTION } from '@/controllers/API/log'
import type { OrgSelection } from '@/types/api/audit'
import { AuditEmptyState } from '../components/AuditEmptyState'
import { OrgFilter } from '../components/OrgFilter'
import type { RuntimeAuditFilters, RuntimeAuditKind } from '@/controllers/API/runtimeAudit'
import { useRuntimeAudit } from './useRuntimeAudit'
import { RuntimeAuditExportDialog } from './RuntimeAuditExportDialog'
import { RuntimeAuditCell } from './RuntimeAuditCell'
import styles from '../AuditFilters.module.css'

interface CandidateProps {
  kind: RuntimeAuditKind
  dimension: 'app' | 'visitor' | 'credential'
  filters: RuntimeAuditFilters
  scopeKey: string
  value?: string
  onChange: (value: string | undefined) => void
}
export function CandidateFilter({ kind, dimension, filters, scopeKey, value, onChange }: CandidateProps) {
  const { t } = useTranslation()
  const labels = useSelectLabels()
  const [search, setSearch] = useState('')
  const query = useInfiniteQuery({ queryKey: ['runtime-audit-candidates', scopeKey, kind, dimension, filters, search], queryFn: ({ pageParam = 0 }) => getRuntimeAuditCandidates(kind, dimension, filters, search, Number(pageParam)), getNextPageParam: (last, pages) => last.has_more ? pages.length * 100 : undefined, retry: false })
  const empty = query.isError ? t('f115.audit.candidatesFailed')
    : dimension === 'visitor' ? t('f115.audit.noVisitors') : t('f115.audit.noCandidates')
  return <div><Select {...labels} allowClear showSearch onSearch={setSearch} loading={query.isInitialLoading} loadingMore={query.isFetchingNextPage} onLoadMore={() => { if (query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage() }}
    emptyText={empty} noMatchText={query.isError ? empty : t('f115.audit.noMatches')} loadingText={t('f115.audit.loading')}
    placeholder={t(`log.runtime.${dimension}`)} aria-label={t(`log.runtime.${dimension}`)} value={value ?? null}
    options={(query.data?.pages.flatMap(page => page.items) ?? []).filter(item => item.id != null && item.id !== '').map(item => ({ value: item.id, label: item.label }))}
    onChange={next => onChange(next == null ? undefined : String(next))} />{query.isError && <div role="alert">{t('f115.audit.candidatesFailed')} <Button size="small" onClick={() => void query.refetch()}>{t('f115.audit.retry')}</Button></div>}</div>
}

interface RecordProps {
  kind: RuntimeAuditKind
  tenantId?: number
  scopeKey: string
  onResetTenant: () => void
}

function recentSevenDays(): DatePickerRange {
  const today = new Date()
  return [format(subDays(today, 6), 'yyyy-MM-dd'), format(today, 'yyyy-MM-dd')]
}

function toTimeFilters(range: DatePickerOpenRange | null): Pick<RuntimeAuditFilters, 'time_range' | 'start_time' | 'end_time'> {
  if (!range) return { time_range: 'all', start_time: undefined, end_time: undefined }
  const [start, end] = range
  return {
    time_range: 'custom',
    start_time: start ? new Date(`${start}T00:00:00`).toISOString() : undefined,
    // Include the final microsecond of the selected day.
    end_time: end ? new Date(`${end}T23:59:59`).toISOString().replace('.000Z', '.999999Z') : undefined,
  }
}

function RuntimeAuditRecords({ kind, tenantId, scopeKey, onResetTenant }: RecordProps) {
  const { t } = useTranslation()
  const datePickerLocale = useDatePickerLocale()
  const paginationLocale = usePaginationLocale()
  const [dateRange, setDateRange] = useState<DatePickerOpenRange | null>(recentSevenDays)
  const [filters, setFilters] = useState<RuntimeAuditFilters>(() => ({ ...toTimeFilters(dateRange), tenant_id: tenantId }))
  const [dateError, setDateError] = useState<DatePickerError | null>(null)
  const [datePickerVersion, setDatePickerVersion] = useState(0)
  // Draft organisation selection; it joins `filters` when the user applies (AC-26).
  const [org, setOrg] = useState<OrgSelection>(EMPTY_ORG_SELECTION)
  const [busy, setBusy] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [createFailed, setCreateFailed] = useState(false)
  const { query, exportQuery, jobId, page, setJob, resetPage, reloadFromFirstPage, setPage } = useRuntimeAudit(kind, filters, scopeKey)
  const handleSearch = () => {
    const nextFilters = withRuntimeOrg({ ...filters, ...toTimeFilters(dateRange) }, org)
    const filterKeys = Object.keys({ ...filters, ...nextFilters }) as (keyof RuntimeAuditFilters)[]
    if (filterKeys.some(key => filters[key] !== nextFilters[key])) {
      // A new time window can leave the chosen visitor outside it; an organisation change must not clear it (AC-26).
      const timeKeys: (keyof RuntimeAuditFilters)[] = ['time_range', 'start_time', 'end_time']
      const timeChanged = timeKeys.some(key => filters[key] !== nextFilters[key])
      setFilters(timeChanged ? { ...nextFilters, visitor_id: undefined } : nextFilters)
    }
    reloadFromFirstPage()
  }
  const handleReset = () => {
    const defaultRange = recentSevenDays()
    setDateRange(defaultRange)
    setDateError(null)
    setDatePickerVersion(version => version + 1)
    setOrg(EMPTY_ORG_SELECTION)
    setFilters({ ...toTimeFilters(defaultRange), tenant_id: tenantId })
    resetPage()
    onResetTenant()
  }
  const handleCreateExport = async () => {
    if (!query.data) return
    setCreateFailed(false)
    setBusy(true)
    try { setJob((await createRuntimeAuditExport(query.data.snapshot_id, tenantId)).export_id) } catch (error) { setCreateFailed(true); showApiError(error) } finally { setBusy(false) }
  }
  const handleExport = () => {
    setExportOpen(true)
    if (!jobId) void handleCreateExport()
  }
  const handleDownload = async () => {
    if (!jobId) return
    setBusy(true)
    try {
      const blob = await downloadRuntimeAuditExport(jobId, tenantId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a'); link.href = url; link.download = `runtime-audit-${kind}.csv`; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { showApiError(error) } finally { setBusy(false) }
  }
  const handleCancel = async () => {
    if (!jobId) return
    setBusy(true)
    try { await cancelRuntimeAuditExport(jobId, tenantId); await exportQuery.refetch() } catch (error) { showApiError(error) } finally { setBusy(false) }
  }
  const fields = kind === 'model'
    ? ['id', 'create_time', 'app_id', 'actor_kind', 'actor_name', 'subject_kind', 'subject_name', 'operator_dept_path', 'credential_mask', 'model_name', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'result', 'error_code', 'http_status', 'latency_ms', 'ttft_ms', 'request_id']
    : kind === 'capability'
      ? ['id', 'create_time', 'app_name', 'app_id', 'credential_mask', 'subject_kind', 'subject_name', 'operator_dept_path', 'capability', 'result', 'error_code', 'latency_ms', 'chunk_count', 'version_id']
      : ['id', 'entry_time', 'app_name_snapshot', 'app_id', 'user_name', 'operator_dept_path', 'request_id']
  return <div className="flex min-h-0 flex-1 flex-col">
    <div className={`${styles.filterContainer} flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pt-2`}>
      <div className={`${styles.filterGrid} shrink-0`}>
        <OrgFilter value={org} onChange={setOrg} tenantId={tenantId ?? null} />
        <DatePicker
          key={datePickerVersion}
          aria-label={t('log.runtime.timeRange')}
          mode="range"
          allowOpenRange
          allowClear
          className={styles.dateRange}
          value={dateRange}
          presets={[{ label: t('log.runtime.recent7d'), value: recentSevenDays() }]}
          onChange={setDateRange}
          onValidationChange={setDateError}
          locale={datePickerLocale}
        />
        <CandidateFilter key={`app-${scopeKey}-${filters.time_range}-${filters.start_time}-${filters.end_time}`} kind={kind} dimension="app" filters={filters} scopeKey={scopeKey} value={filters.app_id} onChange={value => setFilters({ ...filters, app_id: value, visitor_id: undefined })} />
        <CandidateFilter key={`visitor-${scopeKey}-${filters.time_range}-${filters.start_time}-${filters.end_time}-${filters.app_id}-${filters.credential_id}`} kind={kind} dimension="visitor" filters={filters} scopeKey={scopeKey} value={filters.visitor_id?.toString()} onChange={value => setFilters({ ...filters, visitor_id: value ? Number(value) : undefined })} />
        {kind === 'model' && <CandidateFilter key={`credential-${scopeKey}-${filters.time_range}-${filters.app_id}`} kind={kind} dimension="credential" filters={filters} scopeKey={scopeKey} value={filters.credential_id?.toString()} onChange={value => setFilters({ ...filters, credential_id: value ? Number(value) : undefined, visitor_id: undefined })} />}
        <div className={styles.filterActions}>
          <Button onClick={handleReset} variant="outlined" color="default">{t('log.resetButton')}</Button>
          <Button onClick={handleSearch} disabled={Boolean(dateError)}>{t('log.runtime.apply')}</Button>
        </div>
      </div>
      {query.isError ? <div role="alert">{t('log.runtime.loadFailed')} <Button onClick={() => void query.refetch()}>{t('log.runtime.refresh')}</Button></div>
        : query.isInitialLoading ? <p role="status">{t('log.runtime.loading')}</p>
          : <>
            <Table containerClassName={query.data?.items.length ? 'min-h-0 flex-1' : 'shrink-0'}>
              <TableHeader className="sticky top-0 z-10 bg-background-main">
                <TableRow>
                  {fields.map(field => <TableHead key={field} scope="col" className="whitespace-nowrap">{t(`log.runtime.fields.${field}`)}</TableHead>)}
                </TableRow>
              </TableHeader>
              {!!query.data?.items.length && <TableBody>
                {query.data.items.map(row => <TableRow key={String(row.id)}>{fields.map(field => <TableCell key={field}><RuntimeAuditCell kind={kind} field={field} row={row} /></TableCell>)}</TableRow>)}
              </TableBody>}
            </Table>
            {query.data?.items.length === 0 && <AuditEmptyState />}
          </>}
    </div>
    <div className="flex min-h-16 shrink-0 items-center gap-4 pr-4">
      <Button className="shrink-0" variant="outlined" color="default" disabled={busy || !query.data || query.isError} onClick={handleExport}>{t('log.runtime.export')}</Button>
      <Pagination
        className="ml-auto min-w-0"
        total={null}
        hasNextPage={Boolean(query.data?.next_cursor)}
        current={page}
        disabled={query.isFetching}
        locale={paginationLocale}
        onChange={setPage}
      />
    </div>
    <RuntimeAuditExportDialog open={exportOpen} onOpenChange={setExportOpen} kind={kind} filters={filters}
      job={exportQuery.data} busy={busy} createFailed={createFailed} queryFailed={exportQuery.isError}
      onRetryCreate={() => { void handleCreateExport() }} onRefresh={() => { void exportQuery.refetch() }}
      onDownload={() => { void handleDownload() }} onCancel={() => { void handleCancel() }} />
  </div>
}

interface RuntimeAuditPanelProps {
  kind: RuntimeAuditKind
}

export function RuntimeAuditPanel({ kind }: RuntimeAuditPanelProps) {
  const { t } = useTranslation()
  const { user } = useContext(userContext)
  const { appConfig } = useContext(locationContext)
  const labels = useSelectLabels()
  const superAdmin = user?.role === 'admin'
  const { scope, loading } = useAdminScope({ enabled: superAdmin })
  const [tenantId, setTenantId] = useState<number | undefined>()
  const tenants = useQuery({ queryKey: ['runtime-audit-tenants'], queryFn: () => getTenantsApi({ page: 1, page_size: 100 }), enabled: superAdmin && !!appConfig.multiTenantEnabled, retry: false })
  const effectiveTenant = scope.scope_tenant_id ?? tenantId
  const scopeKey = JSON.stringify([user?.user_id, scope.scope_tenant_id, effectiveTenant])
  if (loading) return <p role="status">{t('log.runtime.loading')}</p>
  return <div className="flex h-full min-h-0 flex-1 flex-col gap-4 px-2 pt-2">
    {superAdmin && appConfig.multiTenantEnabled && scope.scope_tenant_id == null && <div className={`${styles.tenantFilter} shrink-0`}>
      <Select {...labels} allowClear placeholder={t('log.runtime.allTenants')} aria-label={t('log.runtime.tenant')} value={tenantId ?? null} options={(tenants.data?.data ?? []).filter(item => item.id != null).map(item => ({ value: item.id, label: item.tenant_name }))} onChange={value => setTenantId(value == null ? undefined : Number(value))} />
    </div>}
    <RuntimeAuditRecords key={`${scopeKey}:${kind}`} kind={kind} tenantId={effectiveTenant} scopeKey={scopeKey} onResetTenant={() => setTenantId(undefined)} />
  </div>
}
