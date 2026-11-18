import { Button, Select, type SelectValue } from '@bisheng/ui'
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels'
import type { ModelPricingRow } from '@/controllers/API/modelPricing'
import { Check, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { creditPricingErrorKey, useCreditSettings } from './useCreditPricing'

// Shared Select items must not use an empty value; this stands for "no explicit base model".
const DEFAULT_BASE = 'default'
const baseReasonKeys: Record<string, string> = {
    base_model_not_allowed: 'model:model.baseModelNotAllowed',
    base_price_missing: 'model:model.basePriceMissing',
    base_price_not_positive: 'model:model.basePriceNotPositive',
}

interface BaseModelPickerProps {
    models: { id: number; label: string; provider: string }[]
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
            <Select {...selectLabels} className="w-96" aria-label={t('dsh.pricing.baseModel')}
                loading={!value} disabled={!value || mutation.isLoading}
                value={value ? value.base_model_id ?? DEFAULT_BASE : null}
                onChange={handleChange}
                options={[
                    { value: DEFAULT_BASE, label: t('dsh.pricing.baseModelDefault') },
                    // Relays often carry the same model name; the provider tells them apart,
                    // also in the trigger once chosen.
                    ...models.map(model => ({ value: model.id, label: t('dsh.pricing.baseModelOption', { model: model.label, provider: model.provider }) })),
                ]} />
            {mutation.isLoading && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label={t('dsh.pricing.saving')} />}
            {mutation.isSuccess && !error && <Check className="size-4 text-green-600" aria-label={t('dsh.pricing.saved')} />}
        </div>
        <p className="text-xs text-muted-foreground">{t('dsh.pricing.baseModelHelp')}</p>
        {unavailable && <p role="status" className="text-xs text-amber-600">{t('dsh.pricing.baseUnavailable')}</p>}
        {value?.base_reason && baseReasonKeys[value.base_reason] &&
            <p className="text-xs text-muted-foreground">{t(baseReasonKeys[value.base_reason])}</p>}
        {error && <p role="alert" className="text-xs text-destructive">{t(error)}</p>}
    </div>
}
