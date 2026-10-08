import type { DshUsageMetrics, DshUsageOverviewPage, DshUsageTimeSummary } from '@/types/dsh'
import { getDshUsageOverview, getDshUsageTimeSummary } from './dsh'

const DAY_MS = 86400000
type Range = { startAt: string; endAt: string }

function splitUsageRange(range: Range, maximumDays: number): Range[] {
    const start = Date.parse(range.startAt)
    const end = Date.parse(range.endAt)
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || end - start > 730 * DAY_MS) {
        throw new Error('Invalid usage history range')
    }
    const maximumDuration = maximumDays * DAY_MS
    if (end - start <= maximumDuration) return [range]
    const segments: Range[] = []
    for (let cursor = start; cursor < end; cursor += maximumDuration) {
        const segmentEnd = Math.min(cursor + maximumDuration, end)
        segments.push({
            startAt: cursor === start ? range.startAt : new Date(cursor).toISOString(),
            endAt: segmentEnd === end ? range.endAt : new Date(segmentEnd).toISOString(),
        })
    }
    return segments
}

export function splitUsageHistoryRange(range: Range): Range[] {
    return splitUsageRange(range, 366)
}

export function splitUsageHourlyRange(range: Range): Range[] {
    return splitUsageRange(range, 7)
}

export function sumUsageMetrics(metrics: DshUsageMetrics[]): DshUsageMetrics {
    if (!metrics.length) throw new Error('Usage history metrics are required')
    const result = { ...metrics[0] }
    for (const key of Object.keys(result) as Array<keyof DshUsageMetrics>) {
        result[key] = metrics.reduce((sum, value) => sum + (value[key] ?? 0), 0)
    }
    if (result.message_count > 0 && result.recorded_usage_count === 0) {
        result.input_tokens = result.output_tokens = result.total_tokens = null
    }
    return result
}

function mergeSummaries(parts: DshUsageTimeSummary[]): DshUsageTimeSummary {
    return {
        ...parts[0],
        end_at: parts.at(-1)!.end_at,
        totals: sumUsageMetrics(parts.map((part) => part.totals)),
        points: parts.flatMap((part) => part.points),
    }
}

export async function getDshUsageHistorySummary(
    userId: string,
    range: Parameters<typeof getDshUsageTimeSummary>[1],
    signal?: AbortSignal,
): Promise<DshUsageTimeSummary> {
    const segments =
        range.granularity === 'hour'
            ? splitUsageHourlyRange(range)
            : splitUsageHistoryRange(range)
    if (segments.length === 1) return getDshUsageTimeSummary(userId, range, signal)
    const granularity = range.granularity === 'hour' ? 'hour' : 'day'
    const parts = await Promise.all(
        segments.map((part) =>
            getDshUsageTimeSummary(userId, { ...range, ...part, granularity }, signal),
        ),
    )
    return mergeSummaries(parts)
}

export async function getDshUsageHistoryOverview(
    query: Parameters<typeof getDshUsageOverview>[0],
    signal?: AbortSignal,
): Promise<DshUsageOverviewPage> {
    const segments =
        query.granularity === 'hour'
            ? splitUsageHourlyRange(query)
            : splitUsageHistoryRange(query)
    if (segments.length === 1) return getDshUsageOverview(query, signal)
    const granularity = query.granularity === 'hour' ? 'hour' : 'day'
    const parts = await Promise.all(
        segments.map((part) => getDshUsageOverview({ ...query, ...part, granularity }, signal)),
    )
    const first = parts[0]
    // Refresh if tenant membership or pagination changes between the two reads.
    if (
        parts.some(
            (part) =>
                part.tenant_id !== first.tenant_id ||
                part.department_id !== first.department_id ||
                part.next_cursor !== first.next_cursor ||
                part.has_more !== first.has_more ||
                part.items.length !== first.items.length ||
                part.items.some((item, index) => {
                    const previous = first.items[index]
                    return (
                        item.user_id !== previous.user_id ||
                        item.user_name !== previous.user_name ||
                        item.department_id !== previous.department_id ||
                        item.department_name !== previous.department_name
                    )
                }),
        )
    ) {
        throw new Error('Usage history membership changed; refresh to retry')
    }
    if (query.includeSummary && parts.some((part) => !part.summary)) {
        throw new Error('Usage history summary is required')
    }
    return {
        ...first,
        end_at: parts.at(-1)!.end_at,
        totals: sumUsageMetrics(parts.map((part) => part.totals)),
        summary: query.includeSummary ? mergeSummaries(parts.map((part) => part.summary!)) : null,
        items: first.items.map((item, index) => ({
            ...item,
            metrics: sumUsageMetrics(parts.map((part) => part.items[index].metrics)),
        })),
    }
}
