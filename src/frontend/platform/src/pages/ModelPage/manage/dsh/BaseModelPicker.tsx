import { Button, Select, type SelectValue } from '@bisheng/ui'
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels'
import type { ModelPricingRow } from '@/controllers/API/modelPricing'
import { Check, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { creditPricingErrorKey, useCreditSettings } from './useCreditPricing'

// Shared Select items must not use an empty value; this stands for "no explicit base model".
const DEFAULT_BASE = 'default'

interface BaseModelPickerProps {
    models: { id: number; label: string }[]
    rows?: Map<number, ModelPricingRow>
}

/** The model shown as 1.00x; it only changes the displayed ratios, never what is charged. */
export function BaseModelPicker({ models, rows }: BaseModelPickerProps) {
    const { t } = useTranslation()
    const selectLabels = useSelectLabels()
    const { settings, mutation } = useCreditSettings()
    const [error, setError] = useState<string | null>(null)
    const value = settings.data

    if (settings.isError) {
        return <p role="alert" className="flex items-center gap-2 text-sm">
            {t('dsh.pricing.unavailable')}
            <Button variant="link" size="small" className="h-auto px-0" onClick={() => void settings.refetch()}>
                {t('dsh.pricing.refresh')}
            </Button>
        </p>
    }

    const effectiveId = value?.effective_base_model_id ?? null
    const baseRow = effectiveId ? rows?.get(effectiveId) : undefined
    // Same rule as the server: a deleted, offline, unpriced or free base model shows no ratios.
    const unavailable = !!value && !!rows && (!baseRow || baseRow.missing || baseRow.hint.free)
    const handleChange = (next: SelectValue | null) => {
        if (!value || mutation.isLoading || next === null) return
        setError(null)
        mutation.mutate(
            { ...value, base_model_id: next === DEFAULT_BASE ? null : Number(next) },
            { onError: reason => setError(creditPricingErrorKey(reason)) },
        )
    }

    return <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium">{t('dsh.pricing.baseModel')}</span>
            <Select {...selectLabels} className="w-72" aria-label={t('dsh.pricing.baseModel')}
                loading={!value} disabled={!value || mutation.isLoading}
                value={value ? value.base_model_id ?? DEFAULT_BASE : null}
                onChange={handleChange}
                options={[
                    { value: DEFAULT_BASE, label: t('dsh.pricing.baseModelDefault') },
                    ...models.map(model => ({ value: model.id, label: model.label })),
                ]} />
            {mutation.isLoading && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label={t('dsh.pricing.saving')} />}
            {mutation.isSuccess && !error && <Check className="size-4 text-green-600" aria-label={t('dsh.pricing.saved')} />}
        </div>
        <p className="text-xs text-muted-foreground">{t('dsh.pricing.baseModelHelp')}</p>
        {unavailable && <p role="status" className="text-xs text-amber-600">{t('dsh.pricing.baseUnavailable')}</p>}
        {error && <p role="alert" className="text-xs text-destructive">{t(error)}</p>}
    </div>
}
