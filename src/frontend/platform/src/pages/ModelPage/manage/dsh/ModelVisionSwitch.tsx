import { Switch, Tag } from '@bisheng/ui'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { saveModelVision } from '@/controllers/API/systemModelSettings'
import type { ModelVisionRow } from '@/controllers/API/modelPricing'
import { showApiError } from '@/controllers/request'

interface ModelVisionSwitchProps {
    modelId: number
    row?: ModelVisionRow
    onSaved: () => Promise<unknown>
}

export function ModelVisionSwitch({ modelId, row, onSaved }: ModelVisionSwitchProps) {
    const { t } = useTranslation('model')
    const [saving, setSaving] = useState(false)
    const handleSave = async (vision: boolean) => {
        if (saving || !row?.can_edit || row.status !== 'available') return
        setSaving(true)
        try {
            await saveModelVision(modelId, vision)
            await onSaved()
        } catch (error) {
            showApiError(error)
        } finally {
            setSaving(false)
        }
    }
    return <div className="flex items-center gap-2">
        <Switch checked={row?.effective ?? false} loading={saving}
            disabled={saving || !row || !row.can_edit || row.status !== 'available'}
            aria-label={t('model.supportsImages')} onCheckedChange={handleSave} />
        {row?.source === 'local_restriction' && <Tag>{t('model.visionLocalRestriction')}</Tag>}
        {row?.status === 'available' && !row.owner_vision && <span className="text-xs text-muted-foreground">{t('model.visionOwnerDisabled')}</span>}
    </div>
}
