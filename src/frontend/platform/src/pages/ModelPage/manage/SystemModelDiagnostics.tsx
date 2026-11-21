import { Alert, Button, Tag } from '@bisheng/ui'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import { getSystemModelSettings, restoreModelInheritance, type SystemModelKey } from '@/controllers/API/systemModelSettings'

interface SystemModelDiagnosticsProps {
    configKey: SystemModelKey
    scopeKey: string
    onRestored: () => void
}

export function SystemModelDiagnostics({ configKey, scopeKey, onRestored }: SystemModelDiagnosticsProps) {
    const { t } = useTranslation('model')
    const client = useQueryClient()
    const [saving, setSaving] = useState(false)
    const [impactEnabled, setImpactEnabled] = useState(false)
    const query = useQuery({
        queryKey: ['system-model-settings', scopeKey],
        queryFn: ({ signal }) => getSystemModelSettings(signal),
        retry: false,
        cacheTime: 0,
        refetchOnWindowFocus: false,
    })
    const section = query.data?.sections.find(item => item.key === configKey)
    const impact = useQuery({
        queryKey: ['system-model-settings-impact', scopeKey],
        queryFn: ({ signal }) => getSystemModelSettings(signal, true),
        enabled: impactEnabled && query.data?.tenant_id === 1,
        retry: false, cacheTime: 0,
    })
    const affected = impact.data?.sections.find(item => item.key === configKey)?.inheritance_impact ?? []
    const invalid = section?.references.filter(item => item.status !== 'available') ?? []
    const handleRestore = () => {
        bsConfirm({
            title: t('model.restoreInheritance'),
            desc: t('model.restoreInheritanceConfirm'),
            okTxt: t('model.restoreInheritance'),
            onOk: (next) => {
                setSaving(true)
                return restoreModelInheritance(configKey)
                    .then(async () => {
                        await client.invalidateQueries({ queryKey: ['system-model-settings', scopeKey] })
                        await client.invalidateQueries({ queryKey: ['system-model-settings-impact'] })
                        await client.invalidateQueries({ queryKey: ['linsightModelEnvelope'] })
                        onRestored()
                        next()
                    })
                    .finally(() => setSaving(false))
            },
        })
    }
    if (query.isError) return <div className="mb-4">
        <Alert type="warning" description={t('model.settingsReadFailed')} />
        <Button variant="link" onClick={() => void query.refetch()}>{t('model.retry')}</Button>
    </div>
    if (!section) return null
    return <section className="mb-4 space-y-3" aria-label={t('model.settingsStatus')}>
        <div className="flex items-center gap-3">
            <Tag>{t(section.inherited_from_root ? 'model.settingsInherited' : 'model.settingsLocal')}</Tag>
            {query.data?.tenant_id !== 1 && !section.inherited_from_root && !section.fallback_blocked &&
                <Button variant="link" size="small" disabled={saving} onClick={handleRestore}>
                    {t('model.restoreInheritance')}
                </Button>}
        </div>
        {query.data?.tenant_id === 1 && <div className="space-y-2">
            <Button variant="link" size="small" loading={impact.isFetching}
                onClick={() => { setImpactEnabled(true); if (impactEnabled) void impact.refetch() }}>
                {t('model.checkInheritanceImpact')}
            </Button>
            {impact.isError && <Alert type="warning" description={t('model.settingsReadFailed')} />}
            {impact.isSuccess && <p className="text-xs text-muted-foreground">{t('model.inheritanceImpactCount', {
                count: new Set(affected.flatMap(item => item.missing_tenant_ids)).size,
            })}</p>}
        </div>}
        {!!invalid.length && <div className="space-y-2">
            <Alert type="warning" description={t('model.settingsInvalidHelp')} />
            <ul className="list-inside list-disc">
                {invalid.map(item => <li key={item.slot_key}>
                    {item.model_name ?? t('model.modelReference', { id: item.model_id })}
                    {' · '}{t(`model.referenceStatus.${item.status}`)}
                </li>)}
            </ul>
        </div>}
    </section>
}
