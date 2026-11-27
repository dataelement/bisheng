import { Button, Input, Modal, Segmented, toast } from '@bisheng/ui'
import type { CreditSettings, PricingCurrency } from '@/controllers/API/modelPricing'
import { saveToolPricingApi, type ToolPricingItem, type ToolPricingMode } from '@/controllers/API/toolPricing'
import { isValidPrice, priceMicro } from '@/pages/ModelPage/manage/modelPricing'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import { AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export type PricedToolChild = {
    id: number
    name: string
    tool_key?: string
}

interface ToolPriceDialogProps {
    tool: PricedToolChild | null
    item?: ToolPricingItem | null
    creditSetting?: CreditSettings | null
    tenantId?: number | null
    onClose: () => void
    onSaved: (saved: ToolPricingItem) => void
    onConflict?: () => void
}

const MICRO = 1_000_000n
const CALL_COUNT_RE = /^[1-9][0-9]*$/

export function isValidCallCount(value: string): boolean {
    if (!CALL_COUNT_RE.test(value.trim())) return false
    const parsed = Number(value.trim())
    return Number.isSafeInteger(parsed) && parsed >= 1 && parsed <= 1_000_000
}

export function normalizeToolPrice(value: string): string {
    const trimmed = value.trim()
    return trimmed === '' ? '0' : trimmed
}

function ceilDivBigInt(numerator: bigint, denominator: bigint): bigint {
    if (numerator <= 0n) return 0n
    return (numerator + denominator - 1n) / denominator
}

export function formatMicroBigInt(value: bigint): string {
    const whole = value / MICRO
    const frac = value % MICRO
    if (frac === 0n) return whole.toString()
    const fracStr = frac.toString().padStart(6, '0').replace(/0+$/, '')
    return `${whole.toString()}.${fracStr}`
}

export function estimateToolCharge(params: {
    pricingMode: ToolPricingMode
    currency: PricingCurrency
    price: string
    callCount: number
    creditSetting?: CreditSettings | null
}): { estimatedCredits: string; estimatedCost: string | null; effectiveCurrency: PricingCurrency } {
    const settingCurrency: PricingCurrency = params.creditSetting?.currency ?? 'CNY'
    const creditValueMicro = BigInt(priceMicro(params.creditSetting?.credit_value ?? '0.01') || 10_000)
    const usdCnyRateMicro = BigInt(priceMicro(params.creditSetting?.usd_cny_rate ?? '6.72') || 6_720_000)
    const normalized = normalizeToolPrice(params.price)
    const pMicro = isValidPrice(normalized) ? BigInt(priceMicro(normalized)) : 0n
    const calls = BigInt(Math.max(1, params.callCount))

    if (pMicro <= 0n) {
        return {
            estimatedCredits: '0',
            estimatedCost: params.pricingMode === 'MONEY' ? '0' : null,
            effectiveCurrency: settingCurrency,
        }
    }

    if (params.pricingMode === 'CREDITS') {
        const creditsMicro = ceilDivBigInt(pMicro, calls)
        const costMicro = ceilDivBigInt(pMicro * creditValueMicro, calls * MICRO)
        return {
            estimatedCredits: formatMicroBigInt(creditsMicro),
            estimatedCost: formatMicroBigInt(costMicro),
            effectiveCurrency: settingCurrency,
        }
    }

    let costMicro: bigint
    let creditsMicro: bigint
    if (params.currency === settingCurrency) {
        costMicro = ceilDivBigInt(pMicro, calls)
        creditsMicro = ceilDivBigInt(pMicro * MICRO, calls * creditValueMicro)
    } else if (params.currency === 'USD' && settingCurrency === 'CNY') {
        costMicro = ceilDivBigInt(pMicro * usdCnyRateMicro, calls * MICRO)
        creditsMicro = ceilDivBigInt(pMicro * usdCnyRateMicro, calls * creditValueMicro)
    } else {
        costMicro = ceilDivBigInt(pMicro * MICRO, calls * usdCnyRateMicro)
        creditsMicro = ceilDivBigInt(pMicro * MICRO * MICRO, calls * usdCnyRateMicro * creditValueMicro)
    }

    return {
        estimatedCredits: formatMicroBigInt(creditsMicro),
        estimatedCost: formatMicroBigInt(costMicro),
        effectiveCurrency: settingCurrency,
    }
}

export function currencySymbol(currency?: PricingCurrency | null): string {
    return currency === 'USD' ? '$' : '¥'
}

export function ToolPriceDialog({
    tool,
    item,
    creditSetting,
    tenantId,
    onClose,
    onSaved,
    onConflict,
}: ToolPriceDialogProps) {
    if (!tool) return null

    return (
        <ToolPriceEditor
            key={tool.id}
            tool={tool}
            item={item}
            creditSetting={creditSetting}
            tenantId={tenantId}
            onClose={onClose}
            onSaved={onSaved}
            onConflict={onConflict}
        />
    )
}

function ToolPriceEditor({
    tool,
    item,
    creditSetting,
    tenantId,
    onClose,
    onSaved,
    onConflict,
}: {
    tool: PricedToolChild
    item?: ToolPricingItem | null
    creditSetting?: CreditSettings | null
    tenantId?: number | null
    onClose: () => void
    onSaved: (saved: ToolPricingItem) => void
    onConflict?: () => void
}) {
    const { t } = useTranslation('tool')
    const defaultMode: ToolPricingMode = item && item.price_micro > 0 ? item.pricing_mode : 'MONEY'
    const defaultCurrency: PricingCurrency = item?.currency ?? creditSetting?.currency ?? 'CNY'

    const [pricingMode, setPricingMode] = useState<ToolPricingMode>(defaultMode)
    const [currency, setCurrency] = useState<PricingCurrency>(defaultCurrency)
    const [callCountInput, setCallCountInput] = useState<string>(String(item?.call_count ?? 1))
    const [priceInput, setPriceInput] = useState<string>(item?.price ?? '0')
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [expectedVersion, setExpectedVersion] = useState(item?.version ?? 0)
    const [waitingForRefresh, setWaitingForRefresh] = useState(false)

    const normalizedPrice = normalizeToolPrice(priceInput)
    const priceValid = isValidPrice(normalizedPrice)
    const callCountValid = isValidCallCount(callCountInput)
    const latestVersion = item?.version ?? 0
    const canSubmit = priceValid && callCountValid && !saving && (!waitingForRefresh || latestVersion > expectedVersion)

    const estimate = estimateToolCharge({
        pricingMode,
        currency,
        price: priceValid ? normalizedPrice : '0',
        callCount: callCountValid ? Number(callCountInput.trim()) : 1,
        creditSetting,
    })

    const handleSave = async () => {
        if (!canSubmit) return
        const version = waitingForRefresh ? latestVersion : expectedVersion
        setSaving(true)
        setError(null)
        setExpectedVersion(version)
        setWaitingForRefresh(false)
        try {
            const saved = await saveToolPricingApi(
                tool.id,
                {
                    pricing_mode: pricingMode,
                    currency: pricingMode === 'MONEY' ? currency : null,
                    price: normalizedPrice,
                    call_count: Number(callCountInput.trim()),
                    version,
                },
                tenantId,
            )
            toast.show({ type: 'success', message: t('pricing.saved') })
            onSaved(saved)
            onClose()
        } catch (err) {
            const errObj = err as { statusCode?: number; status_code?: number } | null | undefined
            const isConflict =
                getDshRequestErrorKey(err) === 'api_errors:26130' ||
                errObj?.statusCode === 26130 ||
                errObj?.status_code === 26130
            if (isConflict) {
                setError(t('pricing.conflict'))
                setWaitingForRefresh(true)
                onConflict?.()
            } else {
                setError(t('pricing.saveFailed'))
            }
        } finally {
            setSaving(false)
        }
    }

    return (
        <Modal
            open
            onOpenChange={(open) => { if (!open) onClose() }}
            size="medium"
            title={`${t('pricing.title')} · ${tool.name}`}
            description={t('pricing.dialogDesc')}
            closeLabel={t('close', { ns: 'bs' })}
            submitting={saving}
            footer={
                <>
                    <Button variant="outlined" color="default" disabled={saving} onClick={onClose}>
                        {t('pricing.cancel')}
                    </Button>
                    <Button loading={saving} disabled={!canSubmit} onClick={() => void handleSave()}>
                        {t(saving ? 'pricing.saving' : 'pricing.save')}
                    </Button>
                </>
            }
        >
            <div className="space-y-4 py-1">
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-[84px_1fr] sm:items-center sm:gap-3">
                    <span className="text-xs font-medium text-muted-foreground">{t('pricing.mode')}</span>
                    <div>
                        <Segmented
                            aria-label={t('pricing.mode')}
                            value={pricingMode}
                            disabled={saving}
                            onChange={(val) => {
                                setPricingMode(val as ToolPricingMode)
                                setError(null)
                            }}
                            options={[
                                { value: 'MONEY', label: t('pricing.modeMoney') },
                                { value: 'CREDITS', label: t('pricing.modeCredits') },
                            ]}
                        />
                    </div>
                </div>

                {pricingMode === 'MONEY' && (
                    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-[84px_1fr] sm:items-center sm:gap-3">
                        <span className="text-xs font-medium text-muted-foreground">{t('pricing.currency')}</span>
                        <div>
                            <Segmented
                                aria-label={t('pricing.currency')}
                                value={currency}
                                disabled={saving}
                                onChange={(val) => {
                                    setCurrency(val as PricingCurrency)
                                    setError(null)
                                }}
                                options={[
                                    { value: 'CNY', label: t('pricing.currencyCNY') },
                                    { value: 'USD', label: t('pricing.currencyUSD') },
                                ]}
                            />
                        </div>
                    </div>
                )}

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="space-y-1.5">
                        <span className="text-xs font-medium text-muted-foreground">{t('pricing.callCount')}</span>
                        <Input
                            aria-label={t('pricing.callCount')}
                            status={callCountValid ? 'default' : 'error'}
                            value={callCountInput}
                            disabled={saving}
                            placeholder="1"
                            suffix={<span className="text-xs text-muted-foreground">{t('pricing.timesUnit')}</span>}
                            onChange={(event) => {
                                setCallCountInput(event.target.value)
                                setError(null)
                            }}
                        />
                        <p className={`text-xs ${callCountValid ? 'text-muted-foreground' : 'text-destructive'}`}>
                            {t(callCountValid ? 'pricing.callCountHint' : 'pricing.callCountInvalid')}
                        </p>
                    </label>

                    <label className="space-y-1.5">
                        <span className="text-xs font-medium text-muted-foreground">
                            {t('pricing.price')} ({pricingMode === 'MONEY' ? currency : t('pricing.creditsUnit')})
                        </span>
                        <Input
                            aria-label={t('pricing.price')}
                            status={priceValid ? 'default' : 'error'}
                            value={priceInput}
                            disabled={saving}
                            placeholder="0"
                            suffix={
                                <span className="text-xs text-muted-foreground">
                                    {pricingMode === 'MONEY'
                                        ? t(currency === 'USD' ? 'pricing.unitUSD' : 'pricing.unitCNY')
                                        : t('pricing.creditsUnit')}
                                </span>
                            }
                            onChange={(event) => {
                                setPriceInput(event.target.value)
                                setError(null)
                            }}
                        />
                        <p className={`text-xs ${priceValid ? 'text-muted-foreground' : 'text-destructive'}`}>
                            {priceValid
                                ? t(pricingMode === 'MONEY' ? 'pricing.priceHintMoney' : 'pricing.priceHintCredits')
                                : t('pricing.priceInvalid')}
                        </p>
                    </label>
                </div>

                {priceValid && callCountValid && (
                    <div className="rounded-lg bg-muted/60 px-3.5 py-2.5 text-xs leading-relaxed text-muted-foreground">
                        {estimate.estimatedCredits === '0' ? (
                            <span>{t('pricing.freeHint')}</span>
                        ) : (
                            <span className="font-medium text-foreground/90">
                                {pricingMode === 'MONEY'
                                    ? t('pricing.estimatedCredits', { credits: estimate.estimatedCredits })
                                    : t('pricing.estimatedCost', {
                                        cost: `${currencySymbol(estimate.effectiveCurrency)}${estimate.estimatedCost ?? '0'}`,
                                        credits: estimate.estimatedCredits,
                                    })}
                            </span>
                        )}
                    </div>
                )}

                {error && (
                    <div
                        role="alert"
                        className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-xs leading-relaxed text-amber-900 dark:border-amber-800/60 dark:bg-amber-950/40 dark:text-amber-200"
                    >
                        <AlertTriangle aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
                        <span>{error}</span>
                    </div>
                )}
            </div>

            <p className="mt-3 border-t pt-3 text-xs leading-relaxed text-muted-foreground">
                {t('pricing.billingNote')}
            </p>
        </Modal>
    )
}
