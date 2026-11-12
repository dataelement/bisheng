import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog'
import type { ModelPricingRow } from '@/controllers/API/modelPricing'
import { Fragment } from 'react'
import { useTranslation } from 'react-i18next'
import { typicalCredits } from '../modelPricing'
import { currencyKey } from './ModelPricingCells'

const PRICE_ROWS = [
    ['input', 'dsh.pricing.input'],
    ['cache_read', 'dsh.pricing.cacheRead'],
    ['cache_write', 'dsh.pricing.cacheWrite'],
    ['output', 'dsh.pricing.output'],
] as const

export type PricedModel = { name: string; row: ModelPricingRow }

interface ModelPriceDialogProps {
    model: PricedModel | null
    /** Price of one credit in the billing currency; the estimate is hidden until it is known. */
    creditValue?: string
    onClose: () => void
}

/** Read-only: prices are edited with the model in model configuration. */
export function ModelPriceDialog({ model, creditValue, onClose }: ModelPriceDialogProps) {
    const { t } = useTranslation()
    const effective = model?.row.effective
    const stored = model?.row.pricing
    const credits = effective && creditValue ? typicalCredits(effective, creditValue) : null
    return <Dialog open={!!model} onOpenChange={open => { if (!open) onClose() }}>
        <DialogContent className="w-[calc(100vw-48px)] max-w-[480px] gap-4 p-5">
            <DialogHeader>
                <DialogTitle>{t('dsh.pricing.priceDialogTitle')} · {model?.name}</DialogTitle>
                <DialogDescription>{t('dsh.pricing.priceDialogHelp')}</DialogDescription>
            </DialogHeader>
            {effective && <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-2 rounded-lg border px-4 py-3 text-sm">
                {PRICE_ROWS.map(([field, label]) => <Fragment key={field}>
                    <dt className="text-muted-foreground">{t(label)}</dt>
                    <dd className="text-right tabular-nums">{effective[field]} {t(currencyKey(effective.currency))}</dd>
                </Fragment>)}
            </dl>}
            {stored && effective && stored.currency !== effective.currency && <p className="text-xs text-muted-foreground">
                {t('dsh.pricing.originalPrice', {
                    input: stored.input,
                    cacheRead: stored.cache_read,
                    cacheWrite: stored.cache_write ?? stored.input,
                    output: stored.output,
                    currency: t(currencyKey(stored.currency)),
                })}
            </p>}
            {credits && <p className="text-sm">{t('dsh.pricing.typical', { credits })}</p>}
            <p className="text-xs text-muted-foreground">{t('dsh.pricing.editHint')}</p>
        </DialogContent>
    </Dialog>
}
