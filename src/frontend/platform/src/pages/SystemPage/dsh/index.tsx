import { Badge } from '@/components/bs-ui/badge'
import { Button } from '@/components/bs-ui/button'
import { getDshLicense } from '@/controllers/API/dsh'
import { getModelListApi } from '@/controllers/API/finetune'
import { userContext } from '@/contexts/userContext'
import { useDshBrowserConfig } from '@/hooks/useDshBrowserConfig'
import { DshDesktopModelConfig } from '@/pages/ModelPage/manage/dsh/DshDesktopModelConfig'
import type { DshSection } from '@/pages/DshPage/sections'
import type { DshLicense, DshOperation, DshOperationRef } from '@/types/dsh'
import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CommercialLicenseDialog } from './CommercialLicenseDialog'
import { AuditHistory } from './AuditHistory'
import { OperationStatus } from './OperationStatus'
import { PolicyView } from './PolicyView'
import { SeatsView } from './SeatsView'
import { SettingsPanel } from './SettingsPanel'
import { licenseStatusKey } from './licensePresentation'

interface DshManagementProps {
    section?: DshSection
    usageToolbarTarget?: HTMLDivElement | null
}

interface DshManagementContentProps {
    config: NonNullable<ReturnType<typeof useDshBrowserConfig>['config']>
    section: DshSection
    canEditSettings: boolean
    tenantName: string
    usageToolbarTarget?: HTMLDivElement | null
}

export function DshManagement({ section = 'license', usageToolbarTarget }: DshManagementProps) {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const { config, failed } = useDshBrowserConfig()

    if (!config) {
        return (
            <div className="flex h-full items-center justify-center">
                <p role={failed ? 'alert' : 'status'}>
                    {t(failed ? 'dsh.unavailable' : 'dsh.loading')}
                </p>
            </div>
        )
    }
    if (!config.management_enabled) {
        return (
            <div className="flex h-full items-center justify-center">
                <p>{t('dsh.managementUnavailable')}</p>
            </div>
        )
    }

    return (
        <div className="flex h-full min-h-0 flex-col px-6 py-5">
            <DshManagementContent
                key={String(config.enabled)}
                config={config}
                section={section}
                canEditSettings={user?.role === 'admin' || !!user?.is_global_super}
                tenantName={user?.tenant_name || user?.leaf_tenant_name || ''}
                usageToolbarTarget={usageToolbarTarget}
            />
        </div>
    )
}

function DshManagementContent({
    config,
    section,
    canEditSettings,
    tenantName,
    usageToolbarTarget,
}: DshManagementContentProps) {
    const [license, setLicense] = useState<DshLicense | null>(null)
    const [licenseError, setLicenseError] = useState(false)
    const [licenseDialogOpen, setLicenseDialogOpen] = useState(false)
    const [references, setReferences] = useState<DshOperationRef[]>([])
    const [operations, setOperations] = useState<Record<string, DshOperation>>({})
    const [revision, setRevision] = useState(0)
    const [auditRevision, setAuditRevision] = useState(0)
    const auditStates = useRef(new Map<string, string>())
    const refreshedOperations = useRef(new Set<string>())
    const activeSection = config.enabled ? section : 'access'

    useEffect(() => {
        if (!config.enabled) return
        const abort = new AbortController()
        setLicenseError(false)
        setLicense(null)
        getDshLicense(abort.signal)
            .then((value) => {
                if (!abort.signal.aborted) setLicense(value)
            })
            .catch(() => {
                if (!abort.signal.aborted) setLicenseError(true)
            })
        return () => abort.abort()
    }, [config.enabled, revision])

    const handleOperation = useCallback(
        (ref: DshOperationRef, result?: DshOperation) => {
            const auditState = ref.rejected ? 'REJECTED' : result?.status || 'REGISTERED'
            if (auditStates.current.get(ref.operation_id) !== auditState) {
                auditStates.current.set(ref.operation_id, auditState)
                setAuditRevision((old) => old + 1)
            }
            setReferences((old) =>
                old.some((item) => item.operation_id === ref.operation_id)
                    ? old.map((item) =>
                          item.operation_id === ref.operation_id
                              ? { ...item, ...ref }
                              : item,
                      )
                    : [ref, ...old],
            )
            if (result) {
                setOperations((old) => ({ ...old, [ref.operation_id]: result }))
                if (
                    result.status === 'SUCCEEDED' &&
                    ['REVOKE', 'REASSIGN'].includes(result.action) &&
                    !refreshedOperations.current.has(ref.operation_id)
                ) {
                    refreshedOperations.current.add(ref.operation_id)
                    setRevision((old) => old + 1)
                }
            }
        },
        [],
    )

    return (
        <div className="min-h-0 flex-1 overflow-y-auto">
            {activeSection === 'license' && config.enabled && (
                <div className="space-y-4">
                    <LicensePanel
                        license={license}
                        error={licenseError}
                        onRefresh={() => setRevision((old) => old + 1)}
                        onAcquire={() => setLicenseDialogOpen(true)}
                    />
                    <SeatsView
                        onOperation={handleOperation}
                        operations={operations}
                        revision={revision}
                    />
                </div>
            )}
            {activeSection === 'models' && config.enabled && <DshModelsView />}
            {activeSection === 'usage' && config.enabled && <PolicyView toolbarTarget={usageToolbarTarget} />}
            {activeSection === 'operations' && config.enabled && (
                <div className="space-y-3">
                    <AuditHistory revision={auditRevision} />
                    {references.filter((ref) => !ref.rejected && !['SUCCEEDED', 'FAILED'].includes(operations[ref.operation_id]?.status)).map((ref) => (
                        <OperationStatus
                            key={ref.operation_id}
                            reference={ref}
                            operation={operations[ref.operation_id]}
                            onUpdate={handleOperation}
                        />
                    ))}
                </div>
            )}
            {activeSection === 'access' && (
                <SettingsPanel settings={config} canEdit={canEditSettings} />
            )}
            <CommercialLicenseDialog
                open={licenseDialogOpen}
                onOpenChange={setLicenseDialogOpen}
                license={license}
                tenantName={tenantName}
            />
        </div>
    )
}

function LicensePanel({
    license,
    error,
    onRefresh,
    onAcquire,
}: {
    license: DshLicense | null
    error: boolean
    onRefresh: () => void
    onAcquire: () => void
}) {
    const { t } = useTranslation()
    const normalizedStatus = license?.status?.toLocaleLowerCase() || 'unknown'

    return (
        <section className="space-y-3 rounded-lg border bg-background p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                    <h2 className="font-semibold">{t('dsh.commercialLicense')}</h2>
                    {license && (
                        <Badge
                            variant="secondary"
                            className={
                                normalizedStatus === 'active'
                                    ? 'text-green-600'
                                    : 'text-amber-600'
                            }
                        >
                            {t(`dsh.licenseStatus.${licenseStatusKey(license)}`, {
                                defaultValue: license.status,
                            })}
                        </Badge>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <Button variant="outline" onClick={onRefresh}>
                        {t('dsh.refresh')}
                    </Button>
                    <Button className="active:scale-[0.97]" onClick={onAcquire}>
                        {t('dsh.getCommercialLicense')}
                    </Button>
                </div>
            </div>
            {!license ? (
                <p role={error ? 'alert' : 'status'}>
                    {t(error ? 'dsh.unavailable' : 'dsh.loading')}
                </p>
            ) : (
                <div className="grid gap-2 text-sm md:grid-cols-2">
                    <p>
                        {t('dsh.seatSummary', {
                            assigned: license.assigned,
                            limit: license.seat_limit,
                            available: license.available,
                        })}
                    </p>
                </div>
            )}
        </section>
    )
}

function DshModelsView() {
    const { t } = useTranslation()
    const [data, setData] = useState<Parameters<typeof DshDesktopModelConfig>[0]['data'] | null>(null)
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
                    {t(error ? 'dsh.modelsUnavailable' : 'dsh.loading')}
                </p>
                {error && (
                    <Button
                        variant="outline"
                        onClick={() => setRevision((old) => old + 1)}
                    >
                        {t('dsh.refresh')}
                    </Button>
                )}
            </div>
        )
    }

    return <DshDesktopModelConfig data={data} />
}
