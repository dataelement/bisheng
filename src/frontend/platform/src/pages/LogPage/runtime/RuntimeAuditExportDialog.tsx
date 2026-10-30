import { Button, Modal } from '@bisheng/ui'
import { useTranslation } from 'react-i18next'
import type { RuntimeAuditExport, RuntimeAuditFilters, RuntimeAuditKind } from '@/controllers/API/runtimeAudit'
import { formatTimestamp } from '@/utils/displayTimestamp'

interface RuntimeAuditExportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kind: RuntimeAuditKind
  filters: RuntimeAuditFilters
  job?: RuntimeAuditExport
  busy: boolean
  createFailed: boolean
  queryFailed: boolean
  onRetryCreate: () => void
  onRefresh: () => void
  onDownload: () => void
  onCancel: () => void
}

export function RuntimeAuditExportDialog({ open, onOpenChange, kind, filters, job, busy,
  createFailed, queryFailed, onRetryCreate, onRefresh, onDownload, onCancel }: RuntimeAuditExportDialogProps) {
  const { t } = useTranslation()
  const retryCreate = createFailed || job?.status === 'failed' || job?.status === 'expired'
  return <Modal open={open} onOpenChange={onOpenChange} title={t('log.runtime.export')} closeLabel={t('close')}
    footer={<>
      <Button color="default" variant="outlined" onClick={() => onOpenChange(false)}>{t('close')}</Button>
      {job && ['pending', 'running'].includes(job.status) && <Button color="danger" variant="outlined" disabled={busy} onClick={onCancel}>{t('log.runtime.cancel')}</Button>}
      {retryCreate && <Button loading={busy} onClick={onRetryCreate}>{t('build.retry')}</Button>}
      {job?.status === 'ready' && !queryFailed && <Button loading={busy} onClick={onDownload}>{t('log.runtime.download')}</Button>}
    </>}
  >
    <div className="space-y-4 py-4">
      <p className="text-body-sm text-text-3">{t('log.runtime.exportBackground')}</p>
      <p>{t(`log.runtime.${kind}Tab`)} · {t(`log.runtime.${filters.time_range}`)}</p>
      {filters.time_range === 'custom' && <p>{formatTimestamp(filters.start_time!)} — {formatTimestamp(filters.end_time!)}</p>}
      {createFailed ? <p role="alert">{t('log.runtime.exportCreateFailed')}</p>
        : queryFailed ? <div role="alert">{t('log.runtime.exportFailed')} <Button variant="link" onClick={onRefresh}>{t('build.retry')}</Button></div>
          : job ? <div role={job.status === 'failed' ? 'alert' : 'status'} className="space-y-2">
            <p>{t(`log.runtime.status.${job.status}`)}</p>
            <p>{t('log.runtime.exportRows', { count: job.final_count ?? job.processed_rows ?? 0 })}</p>
            {job.selection_started_at && <p>{t('log.runtime.selectedAt')}: {formatTimestamp(job.selection_started_at)}</p>}
          </div> : <p role="status">{t('log.runtime.loading')}</p>}
    </div>
  </Modal>
}
