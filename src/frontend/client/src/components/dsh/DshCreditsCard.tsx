import type { DshCredits } from '~/api/dsh'
import { useTranslation } from 'react-i18next'

interface DshCreditsCardProps {
    credits: DshCredits
}

/** This month's shared Chat/Work credits; the server owns every figure, the card only formats them. */
export function DshCreditsCard({ credits }: DshCreditsCardProps) {
    const { t, i18n } = useTranslation()
    // Prices bill fractions of a credit, so two decimals keep small calls visible.
    const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 })
    const format = (value: string | null) => (value == null || value === '' ? '—' : number.format(Number(value)))
    const resetDate = new Intl.DateTimeFormat(i18n.language, {
        month: 'long',
        day: 'numeric',
        timeZone: credits.billing_timezone || 'Asia/Shanghai',
    }).format(new Date(credits.reset_at))
    return (
        <section className="space-y-3 rounded-lg border border-border-base p-4" aria-labelledby="dsh-credits-title">
            <header className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 id="dsh-credits-title" className="text-body font-medium">
                    {t('dsh.creditsTitle')}
                </h3>
                <span className="text-body-sm text-text-3">{t('dsh.creditsReset', { date: resetDate })}</span>
            </header>
            <div className="flex flex-wrap items-end gap-x-10 gap-y-3">
                <div>
                    <p className="text-body-sm text-text-2">{t('dsh.creditsRemaining')}</p>
                    <p className="text-[28px] font-semibold leading-9 tabular-nums" data-credits-remaining>
                        {credits.unlimited ? t('dsh.creditsUnlimited') : format(credits.remaining)}
                    </p>
                </div>
                <p className="text-body-sm text-text-2 tabular-nums">
                    {credits.unlimited
                        ? t('dsh.creditsUsedOnly', { used: format(credits.used) })
                        : t('dsh.creditsDetail', { limit: format(credits.limit), used: format(credits.used) })}
                </p>
            </div>
            <p className="text-body-sm text-text-3">{t('dsh.creditsHelp')}</p>
        </section>
    )
}
