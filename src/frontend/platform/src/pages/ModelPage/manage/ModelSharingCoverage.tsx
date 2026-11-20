import { Alert, Button, Tag } from '@bisheng/ui'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getModelSharingStatus } from '@/controllers/API/systemModelSettings'
import { managementRequestScope } from '@/controllers/managementScope'

interface ModelSharingCoverageProps {
    serverId: number
}

export function ModelSharingCoverage({ serverId }: ModelSharingCoverageProps) {
    const { t } = useTranslation('model')
    const [open, setOpen] = useState(false)
    const query = useQuery({
        queryKey: ['model-sharing-coverage', managementRequestScope(), serverId],
        queryFn: ({ signal }) => getModelSharingStatus(serverId, signal),
        enabled: open, retry: false, cacheTime: 0,
    })
    const status = query.data
    return <div className="space-y-2">
        <Button variant="link" size="small" onClick={() => setOpen(value => !value)}>{t('model.sharingCoverage')}</Button>
        {open && <div className="space-y-2">
            {query.isError && <Button variant="link" size="small" onClick={() => void query.refetch()}>{t('model.settingsReadFailed')}</Button>}
            {status && <>
                <Tag>{t(status.enabled === null ? 'model.sharingUnknown' : status.enabled ? 'model.sharingEnabled' : 'model.sharingDisabled')}</Tag>
                <p>{status.enabled === null
                    ? t('model.sharingExistingCount', { count: status.shared_child_ids.length })
                    : t('model.sharingCoverageCount', { shared: status.shared_child_ids.filter(id => status.expected_child_ids.includes(id)).length, expected: status.expected_child_ids.length })}</p>
                {!!status.missing_child_ids.length && <Alert type="warning" description={t('model.sharingMissing', { count: status.missing_child_ids.length })} />}
                {status.active_plan && <Alert type="warning" description={t('model.sharingPending', status.active_plan)} />}
                <p className="text-xs text-muted-foreground">{t('model.providerSharedLimit')}</p>
            </>}
        </div>}
    </div>
}
