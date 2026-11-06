import { useContext, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Button, Segmented, Select } from '@bisheng/ui'
import { DatePicker } from '@/components/bs-ui/calendar/datePicker'
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table'
import { locationContext } from '@/contexts/locationContext'
import { userContext } from '@/contexts/userContext'
import { useAdminScope } from '@/hooks/useAdminScope'
import { showApiError } from '@/controllers/request'
import { getTenantsApi } from '@/controllers/API/tenant'
import { cancelRuntimeAuditExport, createRuntimeAuditExport, downloadRuntimeAuditExport, getRuntimeAuditCandidates } from '@/controllers/API/runtimeAudit'
import type { RuntimeAuditFilters, RuntimeAuditKind } from '@/controllers/API/runtimeAudit'
import { useRuntimeAudit } from './useRuntimeAudit'
import { RuntimeAuditExportDialog } from './RuntimeAuditExportDialog'
import { RuntimeAuditCell } from './RuntimeAuditCell'

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
  return <div className="min-w-48 flex-1"><Select {...labels} allowClear showSearch onSearch={setSearch} loading={query.isInitialLoading} loadingMore={query.isFetchingNextPage} onLoadMore={() => { if (query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage() }}
    emptyText={empty} noMatchText={query.isError ? empty : t('f115.audit.noMatches')} loadingText={t('f115.audit.loading')}
    placeholder={t(`log.runtime.${dimension}`)} aria-label={t(`log.runtime.${dimension}`)} value={value ?? null}
    options={(query.data?.pages.flatMap(page => page.items) ?? []).filter(item => item.id != null && item.id !== '').map(item => ({ value: item.id, label: item.label }))}
    onChange={next => onChange(next == null ? undefined : String(next))} />{query.isError && <div role="alert">{t('f115.audit.candidatesFailed')} <Button size="small" onClick={() => void query.refetch()}>{t('f115.audit.retry')}</Button></div>}</div>
}

interface RecordProps {
  kind: RuntimeAuditKind
  tenantId?: number
  scopeKey: string
}
function RuntimeAuditRecords({ kind, tenantId, scopeKey }: RecordProps) {
  const { t } = useTranslation()
  const labels = useSelectLabels()
  const [filters, setFilters] = useState<RuntimeAuditFilters>({ time_range: 'recent7d', tenant_id: tenantId })
  const [range, setRange] = useState<RuntimeAuditFilters['time_range']>('recent7d')
  const [start, setStart] = useState<Date>()
  const [end, setEnd] = useState<Date>()
  const [rangeError, setRangeError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [createFailed, setCreateFailed] = useState(false)
  const { query, exportQuery, jobId, page, setJob, next, previous } = useRuntimeAudit(kind, filters, scopeKey)
  const handleRange = () => {
    if (range === 'custom' && (!start || !end || !Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start.getTime() > end.getTime())) { setRangeError(true); return }
    setRangeError(false)
    setFilters({ ...filters, visitor_id: undefined, time_range: range, start_time: range === 'custom' ? start?.toISOString() : undefined, end_time: range === 'custom' ? end?.toISOString() : undefined })
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
    ? ['id', 'create_time', 'app_id', 'actor_kind', 'actor_name', 'subject_kind', 'subject_name', 'credential_mask', 'model_name', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'result', 'error_code', 'http_status', 'latency_ms', 'ttft_ms', 'request_id']
    : kind === 'capability'
      ? ['id', 'create_time', 'app_name', 'app_id', 'credential_mask', 'subject_kind', 'subject_name', 'capability', 'result', 'error_code', 'latency_ms', 'chunk_count', 'version_id']
      : ['id', 'entry_time', 'app_name_snapshot', 'app_id', 'user_name', 'request_id']
  return <div className="flex min-h-0 flex-1 flex-col gap-4 pt-2">
    {kind === 'access' && <p className="text-sm text-muted-foreground">{t('log.runtime.accessHint')}</p>}
    <div className="flex shrink-0 flex-wrap items-center gap-2">
      <div className="min-w-48 flex-1">
        <Select {...labels} value={range} aria-label={t('log.runtime.timeRange')} options={['recent7d', 'custom', 'all'].map(value => ({ value, label: t(`log.runtime.${value}`) }))} onChange={value => setRange(value as RuntimeAuditFilters['time_range'])} />
      </div>
      <CandidateFilter key={`app-${scopeKey}-${filters.time_range}-${filters.start_time}-${filters.end_time}`} kind={kind} dimension="app" filters={filters} scopeKey={scopeKey} value={filters.app_id} onChange={value => setFilters({ ...filters, app_id: value, visitor_id: undefined })} />
      <CandidateFilter key={`visitor-${scopeKey}-${filters.time_range}-${filters.start_time}-${filters.end_time}-${filters.app_id}-${filters.credential_id}`} kind={kind} dimension="visitor" filters={filters} scopeKey={scopeKey} value={filters.visitor_id?.toString()} onChange={value => setFilters({ ...filters, visitor_id: value ? Number(value) : undefined })} />
      {kind === 'model' && <CandidateFilter key={`credential-${scopeKey}-${filters.time_range}-${filters.app_id}`} kind={kind} dimension="credential" filters={filters} scopeKey={scopeKey} value={filters.credential_id?.toString()} onChange={value => setFilters({ ...filters, credential_id: value ? Number(value) : undefined, visitor_id: undefined })} />}
      {range === 'custom' && <>
        <div className="w-56 max-w-full"><DatePicker showTime value={start} placeholder={t('log.runtime.start')} onChange={setStart} /></div>
        <div className="w-56 max-w-full"><DatePicker showTime value={end} placeholder={t('log.runtime.end')} onChange={setEnd} /></div>
      </>}
      <Button onClick={handleRange}>{t('log.runtime.apply')}</Button>
      <Button disabled={busy || !query.data || query.isError} onClick={handleExport}>{t('log.runtime.export')}</Button>
    </div>
    {rangeError && <p role="alert">{t('log.runtime.invalidRange')}</p>}
    <p className="text-sm text-muted-foreground">{t('log.runtime.identityHint')}</p>
    {query.isError ? <div role="alert">{t('log.runtime.loadFailed')} <Button onClick={() => void query.refetch()}>{t('log.runtime.refresh')}</Button></div>
      : query.isInitialLoading ? <p role="status">{t('log.runtime.loading')}</p>
        : <Table containerClassName="min-h-0 flex-1 overflow-auto"><TableHeader className="sticky top-0 z-10 bg-background-main"><TableRow>{fields.map(field => <TableHead key={field}>{t(`log.runtime.fields.${field}`)}</TableHead>)}</TableRow></TableHeader><TableBody>
          {query.data?.items.map(row => <TableRow key={String(row.id)}>{fields.map(field => <TableCell key={field}><RuntimeAuditCell kind={kind} field={field} row={row} /></TableCell>)}</TableRow>)}
          {query.data?.items.length === 0 && <TableRow><TableCell colSpan={fields.length}>{t('log.runtime.empty')}</TableCell></TableRow>}
        </TableBody></Table>}
    <div className="flex shrink-0 items-center gap-2"><Button disabled={page === 1 || query.isFetching} onClick={previous}>{t('log.runtime.previous')}</Button><span>{page}</span><Button disabled={!query.data?.next_cursor || query.isFetching} onClick={next}>{t('log.runtime.next')}</Button><Button onClick={() => void query.refetch()}>{t('log.runtime.refresh')}</Button></div>
    <RuntimeAuditExportDialog open={exportOpen} onOpenChange={setExportOpen} kind={kind} filters={filters}
      job={exportQuery.data} busy={busy} createFailed={createFailed} queryFailed={exportQuery.isError}
      onRetryCreate={() => { void handleCreateExport() }} onRefresh={() => { void exportQuery.refetch() }}
      onDownload={() => { void handleDownload() }} onCancel={() => { void handleCancel() }} />
  </div>
}

export function RuntimeAuditPanel() {
  const { t } = useTranslation()
  const { user } = useContext(userContext)
  const { appConfig } = useContext(locationContext)
  const labels = useSelectLabels()
  const superAdmin = user?.role === 'admin'
  const { scope, loading } = useAdminScope({ enabled: superAdmin })
  const [tenantId, setTenantId] = useState<number | undefined>()
  const [kind, setKind] = useState<RuntimeAuditKind>('model')
  const tenants = useQuery({ queryKey: ['runtime-audit-tenants'], queryFn: () => getTenantsApi({ page: 1, page_size: 100 }), enabled: superAdmin && !!appConfig.multiTenantEnabled, retry: false })
  const effectiveTenant = scope.scope_tenant_id ?? tenantId
  const scopeKey = JSON.stringify([user?.user_id, scope.scope_tenant_id, effectiveTenant])
  if (loading) return <p role="status">{t('log.runtime.loading')}</p>
  return <div className="flex h-full min-h-0 flex-col gap-4 px-2 py-4">
    <div className="flex shrink-0 flex-wrap items-center gap-4">
      <Segmented
        aria-label={t('log.runtime.title')}
        value={kind}
        onChange={value => setKind(value as RuntimeAuditKind)}
        options={(['model', 'capability', 'access'] as const).map(value => ({ value, label: t(`log.runtime.${value}Tab`) }))}
      />
      {superAdmin && appConfig.multiTenantEnabled && scope.scope_tenant_id == null && <div className="w-60 max-w-full">
        <Select {...labels} allowClear placeholder={t('log.runtime.allTenants')} aria-label={t('log.runtime.tenant')} value={tenantId ?? null} options={(tenants.data?.data ?? []).filter(item => item.id != null).map(item => ({ value: item.id, label: item.tenant_name }))} onChange={value => setTenantId(value == null ? undefined : Number(value))} />
      </div>}
    </div>
    <RuntimeAuditRecords key={`${scopeKey}:${kind}`} kind={kind} tenantId={effectiveTenant} scopeKey={scopeKey} />
  </div>
}
