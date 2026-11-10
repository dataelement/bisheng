import { EmptyStateIllustration, StateView } from '@bisheng/ui'
import { useTranslation } from 'react-i18next'

/** Page-level empty result for an audit query. Filters and the table header stay put. */
export function AuditEmptyState() {
  const { t } = useTranslation()
  return (
    <div role="status" className="flex min-h-[320px] flex-1 flex-col">
      <StateView
        className="h-auto flex-1"
        image={<EmptyStateIllustration />}
        title={t('log.emptyTitle')}
        description={t('log.emptyHint')}
      />
    </div>
  )
}
