import type { DshUsageTimeSummary } from '~/api/dsh'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { UsageHeatmap } from './UsageHeatmap'
import { formatUsageTokens } from './usageTokenFormat'

interface UsageSummaryProps {
    summary: DshUsageTimeSummary
}

export function DshUsageCalendar({ summary }: UsageSummaryProps) {
    const { t, i18n } = useTranslation()
    const { totals } = summary
    const [metric, setMetric] = useState<'tokens' | 'messages'>('tokens')
    const tokenTotal =
        totals.total_tokens == null
            ? null
            : formatUsageTokens(totals.total_tokens, i18n.language, t)
    const inputTokens =
        totals.input_tokens == null
            ? null
            : formatUsageTokens(totals.input_tokens, i18n.language, t)
    const outputTokens =
        totals.output_tokens == null
            ? null
            : formatUsageTokens(totals.output_tokens, i18n.language, t)
    return (
        <div className="space-y-5">
            <section
                className="space-y-4 rounded-lg border border-border-base p-4"
                data-usage-calendar-card
            >
                <header className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-body font-medium">
                        {t('dsh.modelUsage')}
                    </h3>
                    <div
                        className="inline-flex rounded-md bg-fill-2 p-0.5"
                        role="group"
                        aria-label={t('dsh.modelUsage')}
                    >
                        {(['tokens', 'messages'] as const).map((item) => (
                            <button
                                key={item}
                                type="button"
                                aria-pressed={metric === item}
                                onClick={() => setMetric(item)}
                                className={`rounded px-3 py-1.5 text-body font-medium ${metric === item ? 'bg-background text-text-1 shadow-sm' : 'text-text-3 hover:text-text-1'}`}
                            >
                                {t(
                                    item === 'tokens'
                                        ? 'dsh.tokenUsage'
                                        : 'dsh.messageCount',
                                )}
                            </button>
                        ))}
                    </div>
                </header>
                <div className="flex flex-wrap items-center gap-x-10 gap-y-6">
                    <div
                        className="w-full min-w-0 max-w-[807px]"
                        data-usage-plot
                    >
                        <UsageHeatmap summary={summary} metric={metric} />
                    </div>
                    <aside
                        className="min-w-0 flex-[1_1_280px]"
                        data-usage-totals
                        data-metric={metric}
                    >
                        <dl>
                            <dt className="text-body text-text-3">
                                {t(
                                    metric === 'tokens'
                                        ? 'dsh.tokenUsage'
                                        : 'dsh.messageCount',
                                )}
                            </dt>
                            <dd
                                className="mt-2 text-h1 font-medium tracking-tight tabular-nums"
                                title={
                                    metric === 'tokens'
                                        ? tokenTotal?.exact
                                        : undefined
                                }
                            >
                                {metric === 'tokens'
                                    ? (tokenTotal?.compact ??
                                      t('dsh.unavailable'))
                                    : totals.message_count.toLocaleString()}
                            </dd>
                        </dl>
                        {metric === 'tokens' && (
                            <p className="mt-3 text-caption text-text-3">
                                {t('dsh.tokenBreakdown', {
                                    input:
                                        inputTokens?.compact ??
                                        t('dsh.unavailable'),
                                    output:
                                        outputTokens?.compact ??
                                        t('dsh.unavailable'),
                                })}
                            </p>
                        )}
                        {totals.missing_usage_count > 0 && (
                            <p
                                role="status"
                                className="mt-3 text-body text-amber-700"
                            >
                                {t('dsh.missingUsageCount', {
                                    count: totals.missing_usage_count,
                                })}
                            </p>
                        )}
                    </aside>
                </div>
            </section>
        </div>
    )
}
