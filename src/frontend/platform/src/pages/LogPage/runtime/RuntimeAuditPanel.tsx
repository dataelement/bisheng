import { useContext, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Button, Input, Select, Tabs } from '@bisheng/ui'
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

interface CandidateProps {
  kind: RuntimeAuditKind
  dimension: 'app' | 'visitor' | 'credential'
  filters: RuntimeAuditFilters
  scopeKey: string
  value?: string
  onChange: (value: string | undefined) => void
}
function CandidateFilter({ kind, dimension, filters, scopeKey, value, onChange }: CandidateProps) {
  const { t } = useTranslation()
  const labels = useSelectLabels()
  const [search, setSearch] = useState('')
  const query = useInfiniteQuery({ queryKey: ['runtime-audit-candidates', scopeKey, kind, dimension, filters, search], queryFn: ({ pageParam = 0 }) => getRuntimeAuditCandidates(kind, dimension, filters, search, Number(pageParam)), getNextPageParam: (last, pages) => last.has_more ? pages.length * 100 : undefined, retry: false })
  return <div><Select {...labels} allowClear showSearch onSearch={setSearch} loading={query.isInitialLoading} loadingMore={query.isFetchingNextPage} onLoadMore={() => { if (query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage() }}
    placeholder={t(`log.runtime.${dimension}`)} aria-label={t(`log.runtime.${dimension}`)} value={value ?? null}
    options={(query.data?.pages.flatMap(page => page.items) ?? []).filter(item => item.id != null && item.id !== '').map(item => ({ value: item.id, label: item.label }))}
    onChange={next => onChange(next == null ? undefined : String(next))} />{query.isError && <p role="alert">{t('log.runtime.loadFailed')}</p>}</div>
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
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [rangeError, setRangeError] = useState(false)
  const [busy, setBusy] = useState(false)
  const { query, exportQuery, jobId, page, setJob, next, previous } = useRuntimeAudit(kind, filters, scopeKey)
  const handleRange = () => {
    if (range === 'custom' && (!start || !end || new Date(start).getTime() > new Date(end).getTime())) { setRangeError(true); return }
    setRangeError(false)
    setFilters({ ...filters, time_range: range, start_time: range === 'custom' ? new Date(start).toISOString() : undefined, end_time: range === 'custom' ? new Date(end).toISOString() : undefined })
  }
  const handleExport = async () => {
    if (!query.data) return
    setBusy(true)
    try { setJob((await createRuntimeAuditExport(query.data.snapshot_id, tenantId)).export_id) } catch (error) { showApiError(error) } finally { setBusy(false) }
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
    try { await cancelRuntimeAuditExport(jobId, tenantId); await exportQuery.refetch() } catch (error) { showApiError(error) }
  }
  const fields = kind === 'model'
    ? ['id', 'create_time', 'app_id', 'actor_kind', 'actor_id', 'actor_name', 'subject_kind', 'subject_id', 'credential_id', 'credential_mask', 'model_name', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'result', 'error_code', 'http_status', 'latency_ms', 'ttft_ms', 'request_id']
    : kind === 'capability'
      ? ['id', 'create_time', 'app_name', 'app_id', 'credential_id', 'subject_kind', 'subject_user_id', 'capability', 'result', 'error_code', 'latency_ms', 'chunk_count', 'version_id']
      : ['id', 'entry_time', 'app_name_snapshot', 'app_id', 'user_name', 'user_id', 'request_id']
  const job = exportQuery.data
  return <div className="space-y-4 pt-2">
    {kind === 'access' && <p className="text-sm text-muted-foreground">{t('log.runtime.accessHint')}</p>}
    <div className="flex flex-wrap gap-2">
      <Select {...labels} value={range} aria-label={t('log.runtime.timeRange')} options={['recent7d', 'custom', 'all'].map(value => ({ value, label: t(`log.runtime.${value}`) }))} onChange={value => setRange(value as RuntimeAuditFilters['time_range'])} />
      {range === 'custom' && <><Input type="datetime-local" aria-label={t('log.runtime.start')} value={start} onChange={event => setStart(event.target.value)} /><Input type="datetime-local" aria-label={t('log.runtime.end')} value={end} onChange={event => setEnd(event.target.value)} /></>}
      <Button onClick={handleRange}>{t('log.runtime.apply')}</Button>
      <CandidateFilter kind={kind} dimension="app" filters={filters} scopeKey={scopeKey} value={filters.app_id} onChange={value => setFilters({ ...filters, app_id: value })} />
      <CandidateFilter kind={kind} dimension="visitor" filters={filters} scopeKey={scopeKey} value={filters.visitor_id?.toString()} onChange={value => setFilters({ ...filters, visitor_id: value ? Number(value) : undefined })} />
      {kind === 'model' && <CandidateFilter kind={kind} dimension="credential" filters={filters} scopeKey={scopeKey} value={filters.credential_id?.toString()} onChange={value => setFilters({ ...filters, credential_id: value ? Number(value) : undefined })} />}
      <Button disabled={busy || !query.data || query.isError} onClick={handleExport}>{t('log.runtime.export')}</Button>
    </div>
    {rangeError && <p role="alert">{t('log.runtime.invalidRange')}</p>}
    {query.isError ? <div role="alert">{t('log.runtime.loadFailed')} <Button onClick={() => void query.refetch()}>{t('log.runtime.refresh')}</Button></div>
      : query.isInitialLoading ? <p role="status">{t('log.runtime.loading')}</p>
        : <div className="overflow-x-auto"><Table><TableHeader><TableRow>{fields.map(field => <TableHead key={field}>{t(`log.runtime.fields.${field}`)}</TableHead>)}</TableRow></TableHeader><TableBody>
          {query.data?.items.map(row => <TableRow key={String(row.id)}>{fields.map(field => <TableCell key={field}>{row[field] == null ? t('log.runtime.unknown') : ['actor_kind', 'subject_kind', 'result', 'capability'].includes(field) ? t(`log.runtime.values.${String(row[field])}`, { defaultValue: String(row[field]) }) : String(row[field])}</TableCell>)}</TableRow>)}
          {query.data?.items.length === 0 && <TableRow><TableCell colSpan={fields.length}>{t('log.runtime.empty')}</TableCell></TableRow>}
        </TableBody></Table></div>}
    <div className="flex items-center gap-2"><Button disabled={page === 1 || query.isFetching} onClick={previous}>{t('log.runtime.previous')}</Button><span>{page}</span><Button disabled={!query.data?.next_cursor || query.isFetching} onClick={next}>{t('log.runtime.next')}</Button><Button onClick={() => void query.refetch()}>{t('log.runtime.refresh')}</Button></div>
    {exportQuery.isError && <p role="alert">{t('log.runtime.exportFailed')}</p>}
    {job && <div role="status" className="flex flex-wrap items-center gap-2"><span>{t(`log.runtime.status.${job.status}`)} · {job.final_count ?? job.processed_rows ?? 0}</span>{job.selection_started_at && <span>{t('log.runtime.selectedAt')}: {job.selection_started_at}</span>}
      {job.status === 'ready' && <Button disabled={busy} onClick={handleDownload}>{t('log.runtime.download')}</Button>}
      {['pending', 'running'].includes(job.status) && <Button onClick={handleCancel}>{t('log.runtime.cancel')}</Button>}
    </div>}
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
  return <div className="space-y-4">
    {superAdmin && appConfig.multiTenantEnabled && scope.scope_tenant_id == null && <Select {...labels} allowClear placeholder={t('log.runtime.allTenants')} aria-label={t('log.runtime.tenant')} value={tenantId ?? null} options={(tenants.data?.data ?? []).filter(item => item.id != null).map(item => ({ value: item.id, label: item.tenant_name }))} onChange={value => setTenantId(value == null ? undefined : Number(value))} />}
    <Tabs activeKey={kind} onChange={value => setKind(value as RuntimeAuditKind)} items={(['model', 'capability', 'access'] as const).map(value => ({ key: value, label: t(`log.runtime.${value}Tab`), children: <RuntimeAuditRecords key={`${scopeKey}:${value}`} kind={value} tenantId={effectiveTenant} scopeKey={scopeKey} /> }))} />
  </div>
}
