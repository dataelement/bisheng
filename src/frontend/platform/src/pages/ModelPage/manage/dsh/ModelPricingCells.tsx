import { Button, Tag, Tooltip } from '@bisheng/ui'
import type { ModelPricingRow, PricingCurrency } from '@/controllers/API/modelPricing'
import { useTranslation } from 'react-i18next'

export const currencyKey = (currency: PricingCurrency) =>
    currency === 'USD' ? 'dsh.pricing.currencyUSD' : 'dsh.pricing.currencyCNY'

const Empty = () => <span className="text-muted-foreground">—</span>

interface CreditRatioCellProps {
    row?: ModelPricingRow
}

export function CreditRatioCell({ row }: CreditRatioCellProps) {
    const { t } = useTranslation()
    if (!row) return <Empty />
    const { ratio, base, free } = row.hint
    return <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        {free
            ? <Tag size="small" color="success">{t('dsh.pricing.free')}</Tag>
            : <span className="tabular-nums">{ratio ? `${ratio}x` : '—'}</span>}
        {base && <Tag size="small" color="brand">{t('dsh.pricing.base')}</Tag>}
    </span>
}

interface PriceSummaryCellProps {
    row?: ModelPricingRow
    modelName: string
    onEdit: () => void
}

export function PriceSummaryCell({ row, modelName, onEdit }: PriceSummaryCellProps) {
    const { t } = useTranslation()
    if (!row) return <Empty />
    const edit = row.read_only || row.can_edit === false
        ? <span className="text-xs text-muted-foreground">{t('model:model.sharedPriceReadonly')}</span>
        : <Button variant="link" size="small" className="h-auto px-0"
        aria-label={`${t('dsh.pricing.editPrice')} · ${modelName}`} onClick={onEdit}>
        {t('dsh.pricing.editPrice')}
    </Button>
    if (row.missing || !row.effective) {
        return <div className="flex min-w-0 flex-col items-start gap-0.5">
            <Tooltip content={t('dsh.pricing.missingHelp')}>
                <span tabIndex={0} className="inline-flex rounded outline-none focus-visible:shadow-focus">
                    <Tag size="small" color="danger">{t('dsh.pricing.missingTag')}</Tag>
                </span>
            </Tooltip>
            {edit}
        </div>
    }
    const { input, output, currency } = row.effective
    return <div className="flex min-w-0 flex-col items-start gap-0.5">
        <span className="flex flex-wrap items-center gap-1.5">
            <span className="tabular-nums">
                {t('dsh.pricing.priceSummary', { input, output, currency: t(currencyKey(currency)) })}
            </span>
            {row.pricing?.source === 'DEFAULT' && <Tag size="small" color="warning">{t('dsh.pricing.defaultTag')}</Tag>}
        </span>
        {edit}
    </div>
}
