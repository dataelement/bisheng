import { LoadingState } from '@/components/bs-icons/loading/LoadingState'
import { Button } from '@bisheng/ui'
import { getModelListApi } from '@/controllers/API/finetune'
import { userContext } from '@/contexts/userContext'
import { useDshBrowserConfig } from '@/hooks/useDshBrowserConfig'
import WorkbenchModel from '@/pages/ModelPage/manage/tabs/WorkbenchModel'
import type { ModelServer } from '@/pages/ModelPage/manage/userModelMetadata'
import type { DshSection } from '@/pages/DshPage/sections'
import { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CreditRulesView } from './CreditRulesView'
import { CreditSettingsPanel } from './CreditSettingsPanel'
import { AuditHistory } from './AuditHistory'
import { PolicyView } from './PolicyView'
import { SettingsPanel } from './SettingsPanel'
import { ModelAuditPanel } from './ModelAuditPanel'

interface DshManagementProps {
    section?: DshSection
}

export function DshManagement({ section = 'credits' }: DshManagementProps) {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const { config, failed } = useDshBrowserConfig()
    if (!config) return failed ? <div role="alert">{t('dsh.unavailable')}</div> : <LoadingState size="page" label={t('dsh.loading')} className="h-full" />
    if (!config.management_enabled) return <p>{t('dsh.managementUnavailable')}</p>
    const billingEnabled = config.credit_billing_enabled ?? config.enabled
    const activeSection = !billingEnabled && (section === 'credits' || section === 'usage') ? 'access' : section
    return <div className="flex h-full min-h-0 flex-col px-2 py-4">
        <div className="min-h-0 flex-1 overflow-y-auto">
            {activeSection === 'models' && <DshModelsView />}
            {activeSection === 'credits' && <div className="space-y-8">
                <CreditSettingsPanel />
                <CreditRulesView />
            </div>}
            {activeSection === 'usage' && <PolicyView />}
            {activeSection === 'model-audit' && <ModelAuditPanel />}
            {activeSection === 'operations' && <AuditHistory revision={0} />}
            {activeSection === 'access' && <SettingsPanel settings={config} canEdit={user?.role === 'admin' || !!user?.is_global_super} />}
        </div>
    </div>
}

function DshModelsView() {
    const { t } = useTranslation()
    const [data, setData] = useState<ModelServer[] | null>(null)
    const [error, setError] = useState(false)
    const [revision, setRevision] = useState(0)

    useEffect(() => {
        let cancelled = false
        setData(null)
        setError(false)
        getModelListApi()
            .then((value) => {
                if (!cancelled) setData(value)
            })
            .catch(() => {
                if (!cancelled) setError(true)
            })
        return () => {
            cancelled = true
        }
    }, [revision])

    if (!data) {
        return (
            <div className="space-y-3">
                <p role={error ? 'alert' : 'status'}>
                    {error ? t('dsh.modelsUnavailable') : <LoadingState label={t('dsh.loading')} />}
                </p>
                {error && (
                    <Button
                        variant="outlined" color="default"
                        onClick={() => setRevision((old) => old + 1)}
                    >
                        {t('dsh.refresh')}
                    </Button>
                )}
            </div>
        )
    }

    return <WorkbenchModel data={data} onBack={() => window.history.back()} />
}
