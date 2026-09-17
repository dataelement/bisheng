import type { DshUsageMetrics, DshUsageTimeBucket, DshUsageTimeSummary } from '@/types/dsh'
import {
    DAY_MS,
    formatShanghaiInstant,
    SHANGHAI_OFFSET_MS,
    twoDigits,
    usageCalendarBounds,
} from './usageRange'

const HOUR_MS = DAY_MS / 24
type HeatmapMode = 'month' | 'calendar'
export type UsageTile = {
    startAt: string
    endAt: string
    row: number
    column: number
    label: string
    point?: DshUsageTimeBucket
    state: 'observed' | 'future' | 'outside'
}
export type UsageHeatmapLayout = {
    mode: HeatmapMode
    rows: number
    columns: number
    hoursPerTile: number
    tiles: UsageTile[]
    columnLabels: Array<{ label: string; column: number }>
    rowLabels: Array<{ label: string; row: number }>
}

const COUNTS = [
    'message_count',
    'qa_count',
    'failed_count',
    'cancelled_count',
    'running_count',
    'usage_unknown_count',
    'recorded_usage_count',
    'missing_usage_count',
] as const
const TOKENS = ['input_tokens', 'output_tokens', 'total_tokens'] as const

function combine(points: DshUsageTimeBucket[]): DshUsageTimeBucket | undefined {
    if (!points.length) return undefined
    const metrics = {} as DshUsageMetrics
    for (const key of COUNTS) metrics[key] = points.reduce((sum, point) => sum + point[key], 0)
    for (const key of TOKENS) {
        metrics[key] =
            metrics.message_count > 0 && metrics.recorded_usage_count === 0
                ? null
                : points.reduce((sum, point) => sum + (point[key] ?? 0), 0)
    }
    const demoTokens = points.reduce((sum, point) => sum + (point.demo_tokens ?? 0), 0)
    return {
        ...metrics,
        start_at: points[0].start_at,
        end_at: points.at(-1)!.end_at,
        ...(demoTokens > 0 ? { demo_tokens: demoTokens } : {}),
    }
}

export function buildUsageHeatmap(summary: DshUsageTimeSummary, now = Date.now()): UsageHeatmapLayout {
    const range = { startAt: summary.start_at, endAt: summary.end_at }
    const { start, end, days } = usageCalendarBounds(range)
    const mode: HeatmapMode = days <= 31 ? 'month' : 'calendar'
    const hoursPerTile = mode === 'calendar' ? 24 : 4
    const step = hoursPerTile * HOUR_MS
    const firstWeekday = (new Date(start + SHANGHAI_OFFSET_MS).getUTCDay() + 6) % 7
    const rows = mode === 'calendar' ? 7 : 6
    const columns = mode === 'calendar' ? Math.ceil((firstWeekday + days) / 7) : days
    const buckets = new Map<number, DshUsageTimeBucket[]>()
    for (const point of summary.points) {
        const anchor = start + Math.floor((Date.parse(point.start_at) - start) / step) * step
        const group = buckets.get(anchor) ?? []
        group.push(point)
        buckets.set(anchor, group)
    }
    const columnLabels: UsageHeatmapLayout['columnLabels'] = []
    const rowLabels: UsageHeatmapLayout['rowLabels'] =
        mode === 'month'
            ? Array.from({ length: 6 }, (_, row) => ({
                  label: `${twoDigits(row * 4)}–${twoDigits((row + 1) * 4)}`,
                  row,
              }))
            : []
    const tiles: UsageTile[] = []
    let previousMonth = ''
    for (let time = start; time < end; time += step) {
        const index = Math.round((time - start) / step)
        const dayIndex = Math.floor((time - start) / DAY_MS)
        const column = mode === 'calendar' ? Math.floor((firstWeekday + dayIndex) / 7) : dayIndex
        const row = mode === 'calendar' ? (firstWeekday + dayIndex) % 7 : index % 6
        const date = new Date(time + SHANGHAI_OFFSET_MS)
        const dateLabel = `${twoDigits(date.getUTCMonth() + 1)}-${twoDigits(date.getUTCDate())}`
        if (mode === 'month') {
            if (index % 6 === 0 && (dayIndex === 0 || dayIndex === days - 1 || dayIndex % 5 === 0))
                columnLabels.push({ label: dateLabel, column })
        } else {
            if (days <= 62 && row === 0 && column % 3 === 0) columnLabels.push({ label: dateLabel, column })
            else if (days > 62) {
                const month = `${date.getUTCFullYear()}-${twoDigits(date.getUTCMonth() + 1)}`
                if (month !== previousMonth && column !== columnLabels.at(-1)?.column) {
                    columnLabels.push({ label: month, column })
                    previousMonth = month
                }
            }
        }
        const point = combine(buckets.get(time) ?? [])
        const state =
            time >= Math.min(Date.parse(summary.end_at), now)
                ? 'future'
                : time + step <= Date.parse(summary.start_at)
                  ? 'outside'
                  : 'observed'
        tiles.push({
            startAt: formatShanghaiInstant(time),
            endAt: formatShanghaiInstant(time + step),
            row,
            column,
            point,
            state,
            label: '',
        })
    }
    return {
        mode,
        rows,
        columns,
        hoursPerTile,
        tiles,
        columnLabels,
        rowLabels,
    }
}
