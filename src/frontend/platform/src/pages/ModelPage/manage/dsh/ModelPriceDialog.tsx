import { Button, toast } from '@bisheng/ui'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog'
import type { CreditSettings, ModelPricing, ModelPricingRow } from '@/controllers/API/modelPricing'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { confirmPriceChanges } from '../ModelPriceConfirm'
import { ModelPriceFields } from '../ModelPriceFields'
import { draftTypicalCredits, isPricingValid, samePrices } from '../modelPricing'
import { saveFailureMessage } from '../modelSavePayload'
import { useSaveModelPricing } from './useCreditPricing'

export type PricedModel = {
    id: number
    /** Display label shown in the title. */
    name: string
    /** Vendor model name and provider type, for the price-catalog lookup. */
    modelName: string
    providerType?: string
    row: ModelPricingRow
}

interface ModelPriceDialogProps {
    model: PricedModel | null
    /** Billing currency, credit value and rate; the estimate is hidden until they are known. */
    settings?: CreditSettings
    onClose: () => void
}

/** Edit a model's price where its ratio is shown, instead of in the provider form. */
export function ModelPriceDialog({ model, settings, onClose }: ModelPriceDialogProps) {
    return <Dialog open={!!model} onOpenChange={open => { if (!open) onClose() }}>
        <DialogContent className="w-[calc(100vw-48px)] max-w-[640px] gap-4 p-5">
            {model && <PriceEditor key={model.id} model={model} settings={settings} onClose={onClose} />}
        </DialogContent>
    </Dialog>
}

function editable(pricing: ModelPricing | null): ModelPricing | undefined {
    if (!pricing) return undefined
    const { currency, input, cache_read, cache_write, output, revision } = pricing
    return { currency, input, cache_read, cache_write: cache_write ?? null, output, revision }
}

function PriceEditor({ model, settings, onClose }: { model: PricedModel; settings?: CreditSettings; onClose: () => void }) {
    const { t } = useTranslation()
    const stored = editable(model.row.pricing)
    // A model without a price starts from the catalog (or zero) suggestion the fields fetch.
    const [draft, setDraft] = useState<ModelPricing | undefined>(stored)
    const [error, setError] = useState<string | null>(null)
    const save = useSaveModelPricing()
    const changed = !!draft && (!stored || !samePrices(draft, stored))
    const credits = draft && settings ? draftTypicalCredits(draft, settings) : null

    const handleSave = async () => {
        if (!draft || !changed || !isPricingValid(draft)) return
        if (!(await confirmPriceChanges([{ before: stored, after: draft }]))) return
        setError(null)
        save.mutate({ modelId: model.id, pricing: { ...draft, revision: stored?.revision } }, {
            onSuccess: () => {
                toast.show({ type: 'success', message: t('dsh.pricing.priceSaved') })
                onClose()
            },
            onError: reason => setError(saveFailureMessage(reason, t('dsh.pricing.saveFailed')) ?? t('dsh.pricing.saveFailed')),
        })
    }

    return <>
        <DialogHeader>
            <DialogTitle>{t('dsh.pricing.priceDialogTitle')} · {model.name}</DialogTitle>
            <DialogDescription>{t('dsh.pricing.priceDialogHelp')}</DialogDescription>
        </DialogHeader>
        <ModelPriceFields value={draft} providerType={model.providerType ?? ''} modelName={model.modelName}
            onChange={value => { setDraft(value); setError(null) }} />
        {credits && <p className="text-sm">{t('dsh.pricing.typical', { credits })}</p>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
            <Button variant="outlined" color="default" onClick={onClose}>{t('dsh.pricing.cancel')}</Button>
            <Button loading={save.isLoading} disabled={!changed || !draft || !isPricingValid(draft)} onClick={() => void handleSave()}>
                {t('dsh.pricing.save')}
            </Button>
        </DialogFooter>
    </>
}
