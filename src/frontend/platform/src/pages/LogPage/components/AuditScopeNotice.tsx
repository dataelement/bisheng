import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert } from '@bisheng/ui'
import { getAuditScopeApi, type AuditScope } from '@/controllers/API/log'
import { auditScopeDescription } from './auditScopeDescription'

export function AuditScopeNotice() {
  const { t } = useTranslation()
  const [scope, setScope] = useState<AuditScope | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    getAuditScopeApi()
      .then((next) => {
        if (active) setScope(next)
      })
      .catch(() => {
        if (active) setFailed(true)
      })
    return () => {
      active = false
    }
  }, [])

  if (failed) return <Alert className="shrink-0" type="warning" description={t('log.scope.loadFailed')} />
  if (!scope) return null
  return <Alert className="shrink-0" description={auditScopeDescription(scope, t)} />
}
