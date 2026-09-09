import type { DshLastCall, DshUsage } from '@/types/dsh'
import { useTranslation } from 'react-i18next'
import { dshTime } from './common'

interface UsageSummaryProps {
    usage: DshUsage | null
    modelNames: Record<string, string>
    lastCall: DshLastCall | null
    lastCallSource: 'persisted' | 'unavailable'
}
export function UsageSummary({
    usage,
    modelNames,
    lastCall,
    lastCallSource,
}: UsageSummaryProps) {
    const { t } = useTranslation()
    const remaining =
        usage?.model_limits != null && usage.models != null
            ? Object.entries(usage.model_limits).reduce<number | null>(
                  (total, [id, limit]) => {
                      const used = usage.models?.[id]
                      return total == null || used == null
                          ? null
                          : total + Math.max(limit - used, 0)
                  },
                  0,
              )
            : null
    const modelIds = new Set([
        ...Object.keys(usage?.model_limits ?? {}),
        ...Object.keys(usage?.models ?? {}),
    ])
    return (
        <section className="space-y-2 rounded-lg border p-4">
            <h3 className="font-semibold">{t('dsh.usage')}</h3>
            {!usage ? (
                <p>{t('dsh.usageUnavailable')}</p>
            ) : (
                <>
                    <p>
                        {t('dsh.usageSummary', {
                            used: usage.used ?? t('dsh.unavailable'),
                            limit: usage.limit,
                            remaining: remaining ?? t('dsh.unavailable'),
                        })}
                    </p>
                    <p>
                        {usage.month} · {usage.billing_timezone}
                    </p>
                    <p>
                        {t('dsh.source')}: {t(`dsh.${usage.source}`)} ·{' '}
                        {dshTime(usage.as_of)} · {usage.quota_state}
                    </p>
                    {(usage.unknown_pending === null ||
                        (usage.unknown_pending ?? 0) > 0) && (
                        <p role="status">{t('dsh.unknownHelp')}</p>
                    )}
                    <p className="text-sm text-muted-foreground">
                        {t('dsh.independentQuota')}
                    </p>
                    {[...modelIds].map((id) => {
                        const limit = usage.model_limits?.[id]
                        const used = usage.models?.[id] ?? null
                        return (
                            <p key={id}>
                                {modelNames[id] || id}:{' '}
                                {t('dsh.usageSummary', {
                                    used: used ?? t('dsh.unavailable'),
                                    limit:
                                        limit ??
                                        t(
                                            usage.model_limits == null
                                                ? 'dsh.unavailable'
                                                : 'dsh.notConfigured',
                                        ),
                                    remaining:
                                        limit == null || used == null
                                            ? t('dsh.unavailable')
                                            : Math.max(limit - used, 0),
                                })}
                            </p>
                        )
                    })}
                </>
            )}
            <h3 className="font-semibold">{t('dsh.lastCall')}</h3>
            {lastCallSource === 'unavailable' ? (
                <p>{t('dsh.lastCallUnavailable')}</p>
            ) : !lastCall ? (
                <p>{t('dsh.noLastCall')}</p>
            ) : (
                <>
                    <p>
                        {modelNames[String(lastCall.model_id)] ||
                            String(lastCall.model_id)}{' '}
                        · {t(`dsh.callStatus.${lastCall.status}`)}
                    </p>
                    <p>
                        {t('dsh.callStarted')}: {dshTime(lastCall.started_at)} ·{' '}
                        {t('dsh.callFinished')}: {dshTime(lastCall.finished_at)}
                    </p>
                    <p>
                        {t('dsh.callTokens')}:{' '}
                        {lastCall.total_tokens ?? t('dsh.unknownUsage')}
                    </p>
                    <p className="break-all">
                        {t('dsh.requestId')}: {lastCall.request_id}
                    </p>
                    <p className="text-sm text-muted-foreground">
                        {t('dsh.callProjection')}:{' '}
                        {dshTime(lastCall.projected_at)}
                    </p>
                </>
            )}
        </section>
    )
}
