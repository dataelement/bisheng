import { Tooltip } from '@bisheng/ui'
import { useTranslation } from 'react-i18next'
import type { RuntimeAuditKind, RuntimeAuditRow } from '@/controllers/API/runtimeAudit'
import { formatTimestamp } from '@/utils/displayTimestamp'

interface RuntimeAuditCellProps {
  kind: RuntimeAuditKind
  field: string
  row: RuntimeAuditRow
}

function text(row: RuntimeAuditRow, field: string) {
  const value = row[field]
  return typeof value === 'string' && value.trim() ? value : undefined
}

export function RuntimeAuditCell({ kind, field, row }: RuntimeAuditCellProps) {
  const { t } = useTranslation()
  let label: string | undefined
  let identifier: RuntimeAuditRow[string] | undefined
  if (field === 'actor_name') {
    identifier = row.actor_id
    label = text(row, field) ?? (identifier != null ? t('log.runtime.callerWithId', { id: identifier }) : undefined)
  } else if (field === 'subject_name') {
    identifier = kind === 'model' ? row.subject_id : row.subject_user_id
    label = row.subject_kind === 'app_self'
      ? t('log.runtime.values.app_self')
      : text(row, field) ?? (identifier != null
        ? t(row.subject_kind === 'service_account' ? 'log.runtime.accountWithId' : 'log.runtime.personWithId', { id: identifier })
        : undefined)
  } else if (field === 'user_name') {
    identifier = row.user_id
    label = text(row, field) ?? (identifier != null ? t('log.runtime.personWithId', { id: identifier }) : undefined)
  } else if (field === 'credential_mask') {
    identifier = row.credential_id
    label = text(row, field) ?? (identifier != null ? t('log.runtime.keyWithId', { id: identifier }) : undefined)
  } else if (row[field] == null) {
    label = t(field === 'chunk_count' && row.result === 'refused' ? 'log.runtime.noResult' : 'log.runtime.notRecorded')
  } else if (['actor_kind', 'subject_kind', 'result', 'capability'].includes(field)) {
    label = t(`log.runtime.values.${String(row[field])}`, { defaultValue: String(row[field]) })
  } else if (['entry_time', 'create_time'].includes(field)) {
    label = formatTimestamp(String(row[field]))
  } else {
    label = String(row[field])
  }
  label ??= t('log.runtime.notRecorded')
  return identifier == null ? <>{label}</> : (
    <Tooltip content={t('log.runtime.identifier', { id: identifier })}>
      <span tabIndex={0}>{label}</span>
    </Tooltip>
  )
}
