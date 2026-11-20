import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import { Button, Input, Segmented } from '@bisheng/ui'
import type { PricingCurrency } from '@/controllers/API/modelPricing'
import { isValidPrice, priceMicro } from '@/pages/ModelPage/manage/modelPricing'
import { creditPricingErrorKey, useCreditSettings } from '@/pages/ModelPage/manage/dsh/useCreditPricing'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

// Same bounds as the server (micro-units): one credit 0.0001-100, USD/CNY rate 0.01-100.
const CREDIT_VALUE_RANGE = [100, 100_000_000] as const
const RATE_RANGE = [10_000, 100_000_000] as const
const inRange = (value: string, [low, high]: readonly [number, number]) =>
    isValidPrice(value) && priceMicro(value) >= low && priceMicro(value) <= high

// Unset fields show the saved value. Switching the currency keeps the credit value's number
// (1 credit = 0.01 CNY becomes 1 credit = 0.01 USD), so each credit is suddenly worth a different
// amount of money: the switch asks for confirmation first, and still needs Save to apply.
type Draft = { currency?: PricingCurrency; creditValue?: string; rate?: string }
const EMPTY_DRAFT: Draft = {}

export function CreditSettingsPanel() {
    const { t } = useTranslation()
    const fieldId = useId()
    const { settings, mutation } = useCreditSettings()
    const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
    const [error, setError] = useState<string | null>(null)
    const saved = settings.data

    if (!saved) {
        return <section className="space-y-2">
            <h3 className="text-sm font-medium">{t('dsh.pricing.settings')}</h3>
            <p role={settings.isError ? 'alert' : 'status'} className="flex items-center gap-2 text-sm">
                {settings.isError ? t('dsh.pricing.unavailable') : <LoadingState label={t('dsh.loading')} />}
                {settings.isError && <Button variant="link" size="small" className="h-auto px-0"
                    onClick={() => void settings.refetch()}>{t('dsh.pricing.refresh')}</Button>}
            </p>
        </section>
    }

    const currency = draft.currency ?? saved.currency
    const rate = draft.rate ?? saved.usd_cny_rate
    const creditValue = draft.creditValue ?? saved.credit_value
    const creditValid = inRange(creditValue, CREDIT_VALUE_RANGE)
    const rateValid = inRange(rate, RATE_RANGE)
    const dirty = currency !== saved.currency || creditValue !== saved.credit_value || rate !== saved.usd_cny_rate
    const pending = mutation.isLoading
    const currencyName = (value: PricingCurrency) => t(value === 'USD' ? 'dsh.pricing.currencyUSD' : 'dsh.pricing.currencyCNY')
    const edit = (changes: Partial<Draft>) => {
        setDraft(old => ({ ...old, ...changes }))
        setError(null)
        mutation.reset()
    }
    const handleCurrencyChange = (next: PricingCurrency) => {
        if (next === currency) return
        // Going back to the saved currency only undoes an unsaved switch: nothing to warn about.
        if (next === saved.currency) return edit({ currency: undefined })
        const usdCny = rateValid ? rate : saved.usd_cny_rate
        const times = next === 'USD' ? usdCny : String(Number((1 / Number(usdCny)).toFixed(4)))
        bsConfirm({
            // Not destructive (it can be switched back), so the primary tone rather than the red delete one.
            variant: 'default',
            title: t('dsh.pricing.switchCurrencyTitle', { currency: currencyName(next) }),
            desc: t('dsh.pricing.switchCurrencyDesc', {
                value: creditValue, from: currencyName(currency), to: currencyName(next), rate: usdCny, times,
            }),
            canelTxt: t('dsh.pricing.switchCurrencyCancel'),
            okTxt: t('dsh.pricing.switchCurrencyOk'),
            onOk: close => {
                edit({ currency: next })
                close()
            },
        })
    }
    const handleSave = () => {
        if (!dirty || !creditValid || !rateValid || pending) return
        setError(null)
        mutation.mutate(
            { ...saved, currency, credit_value: creditValue, usd_cny_rate: rate },
            {
                onSuccess: () => setDraft(EMPTY_DRAFT),
                onError: reason => setError(creditPricingErrorKey(reason)),
            },
        )
    }

    return <section className="max-w-[720px] space-y-4">
        <div>
            <h3 className="text-sm font-medium">{t('dsh.pricing.settings')}</h3>
            <p className="mt-1 text-xs text-muted-foreground">{t('dsh.pricing.settingsHelp')}</p>
        </div>
        <div className="space-y-1">
            <label htmlFor={`${fieldId}-credit`} className="text-sm">{t('dsh.pricing.creditValue')}</label>
            {/* The billing currency sits right after the value it denominates (two options, so a segmented control). */}
            <div className="flex items-center gap-2">
                <Input id={`${fieldId}-credit`} className="w-48" inputMode="decimal" value={creditValue} disabled={pending}
                    status={creditValid ? undefined : 'error'} aria-describedby={`${fieldId}-credit-help`}
                    onChange={event => edit({ creditValue: event.target.value.trim() })} />
                <Segmented aria-label={t('dsh.pricing.currency')} value={currency} disabled={pending}
                    onChange={value => handleCurrencyChange(value as PricingCurrency)}
                    options={[
                        { value: 'CNY', label: currencyName('CNY') },
                        { value: 'USD', label: currencyName('USD') },
                    ]} />
            </div>
            <p id={`${fieldId}-credit-help`} role={creditValid ? undefined : 'alert'}
                className={`text-xs ${creditValid ? 'text-muted-foreground' : 'text-destructive'}`}>
                {creditValid
                    ? t('dsh.pricing.creditValueHelp', { value: creditValue, currency: currencyName(currency) })
                    : t('dsh.pricing.creditValueInvalid')}
            </p>
        </div>
        <div className="space-y-1">
            <label htmlFor={`${fieldId}-rate`} className="text-sm">{t('dsh.pricing.rate')}</label>
            <Input id={`${fieldId}-rate`} className="w-48" inputMode="decimal" value={rate} disabled={pending}
                status={rateValid ? undefined : 'error'} aria-describedby={`${fieldId}-rate-help`}
                onChange={event => edit({ rate: event.target.value.trim() })} />
            <p id={`${fieldId}-rate-help`} role={rateValid ? undefined : 'alert'}
                className={`text-xs ${rateValid ? 'text-muted-foreground' : 'text-destructive'}`}>
                {t(rateValid ? 'dsh.pricing.rateHelp' : 'dsh.pricing.rateInvalid')}
            </p>
        </div>
        <div className="flex items-center gap-2">
            <Button onClick={handleSave} disabled={!dirty || !creditValid || !rateValid || pending}>
                {t(pending ? 'dsh.pricing.saving' : 'dsh.pricing.save')}
            </Button>
            {dirty && <Button variant="outlined" color="default" disabled={pending} onClick={() => { setDraft(EMPTY_DRAFT); setError(null) }}>
                {t('dsh.pricing.cancel')}
            </Button>}
            {mutation.isSuccess && !dirty && <span role="status" className="text-xs text-muted-foreground">{t('dsh.pricing.saved')}</span>}
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{t(error)}</p>}
    </section>
}
