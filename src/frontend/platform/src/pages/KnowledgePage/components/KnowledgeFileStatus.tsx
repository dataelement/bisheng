import { Button,Tag,Tooltip,type TagColor } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { resolveKnowledgeParseFailure } from '../knowledgeParseFailureMessage'

export const FILE_STATUSES: Record<number, { labelKey: string; color: TagColor }> = {
    1: { labelKey: 'parsing', color: 'brand' },
    2: { labelKey: 'completed', color: 'success' },
    3: { labelKey: 'parseFailed', color: 'danger' },
    4: { labelKey: 'parsing', color: 'brand' },
    5: { labelKey: 'queuing', color: 'warning' },
    6: { labelKey: 'timeout', color: 'danger' },
    7: { labelKey: 'violation', color: 'danger' },
}

interface StatusIndicatorProps {
    status: number
    remark?: string
}

export function StatusIndicator({ status, remark }: StatusIndicatorProps) {
    const { t } = useTranslation()
    const config = FILE_STATUSES[status]
    const reason = useMemo(() => {
        const text = remark?.trim() || ''
        if (!text.startsWith('{')) return text
        try {
            const parsed: unknown = JSON.parse(text)
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return text
            const obj = parsed as Record<string, unknown>
            if (status === 7 && obj.reason === 'sensitive_check') {
                const words = Array.isArray(obj.hits) ? obj.hits.map((hit: unknown) => {
                    if (!hit || typeof hit !== 'object') return ''
                    return String((hit as Record<string, unknown>).word ?? '').trim()
                }).filter(Boolean) : []
                return words.length
                    ? `${t('sensitiveViolationMessagePrefix', { ns: 'knowledge' })}{${[...new Set(words)].join(',')}}${t('sensitiveViolationMessageSuffix', { ns: 'knowledge' })}`
                    : t('sensitiveViolationMessage', { ns: 'knowledge' })
            }
            const media = resolveKnowledgeParseFailure(obj, t)
            if (media) return media
            const data = obj.data && typeof obj.data === 'object' && !Array.isArray(obj.data) ? obj.data : {}
            return t(`api_errors:${obj.status_code}`, { ...data, defaultValue: String(obj.status_message || t('api_errors:fallback')) })
        } catch {
            return text
        }
    }, [remark, status, t])
    if (!config) return null
    const label = <Tag size="small" dot color={config.color} className="shrink-0 whitespace-nowrap">
        {t(config.labelKey, { ns: 'knowledge' })}
    </Tag>
    if (status === 7 && reason) return <Tooltip content={reason}>{label}</Tooltip>
    const hint = status === 6 ? t('timeoutTip', { ns: 'knowledge' }) : status === 3 ? reason : ''
    return <span className="inline-flex items-center gap-1 whitespace-nowrap">
        {label}
        {hint && <Tooltip content={hint}>
            <Button type="button" size="small" variant="ghost" iconOnly color="danger" aria-label={hint}>
                <Outlined.Attention />
            </Button>
        </Tooltip>}
    </span>
}
