import { describe, expect, it } from 'vitest'
import type { DshUsageMetrics, DshUsageTimeSummary } from '@/types/dsh'
import { buildUsageHeatmap } from './usageHeatmapData'
import {
    DAY_MS,
    formatShanghaiInstant,
    usageGranularity,
    usagePresetRange,
} from './usageRange'

const empty: DshUsageMetrics = {
    message_count: 0,
    qa_count: 0,
    failed_count: 0,
    cancelled_count: 0,
    running_count: 0,
    usage_unknown_count: 0,
    recorded_usage_count: 0,
    missing_usage_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
}
function series(startAt: string, endAt: string, granularity: 'day' | 'hour'): DshUsageTimeSummary {
    const step = granularity === 'hour' ? DAY_MS / 24 : DAY_MS
    const start = Date.parse(startAt)
    const end = Date.parse(endAt)
    return {
        start_at: startAt,
        end_at: endAt,
        granularity,
        timezone: 'Asia/Shanghai',
        totals: { ...empty },
        points: Array.from({ length: Math.ceil((end - start) / step) }, (_, index) => ({
            ...empty,
            start_at: formatShanghaiInstant(start + index * step),
            end_at: formatShanghaiInstant(Math.min(start + (index + 1) * step, end)),
        })),
    }
}

describe('time range and tile resolution', () => {
    it('uses one date per column and six four-hour rows, preserving totals and unknown usage', () => {
        const data = series('2026-09-09T00:00:00+08:00', '2026-09-16T00:00:00+08:00', 'hour')
        Object.assign(data.points[0], {
            message_count: 1,
            qa_count: 1,
            recorded_usage_count: 1,
            input_tokens: 8,
            output_tokens: 2,
            total_tokens: 10,
        })
        Object.assign(data.points[1], {
            message_count: 1,
            failed_count: 1,
            missing_usage_count: 1,
            input_tokens: null,
            output_tokens: null,
            total_tokens: null,
        })
        Object.assign(data.points[2], {
            message_count: 1,
            qa_count: 1,
            recorded_usage_count: 1,
            input_tokens: 20,
            output_tokens: 10,
            total_tokens: 30,
        })
        const layout = buildUsageHeatmap(data)
        expect([layout.rows, layout.columns, layout.hoursPerTile]).toEqual([6, 7, 4])
        expect(layout.tiles).toHaveLength(42)
        expect(layout.tiles[0].point).toMatchObject({
            total_tokens: 40,
            message_count: 3,
            missing_usage_count: 1,
        })
        expect(layout.tiles.reduce((sum, tile) => sum + (tile.point?.total_tokens ?? 0), 0)).toBe(40)
        expect(layout.tiles[41].point?.end_at).toBe(data.end_at)
        expect(layout.tiles[5]).toMatchObject({ row: 5, column: 0 })
        expect(layout.tiles[6]).toMatchObject({ row: 0, column: 1 })
        expect(layout.tiles[41]).toMatchObject({ row: 5, column: 6 })
        expect(layout.rowLabels).toEqual([{ label: '00:00', row: 0 }, { label: '12:00', row: 3 }, { label: '24:00', row: 6 }])
        expect(layout.columnLabels.at(-1)).toEqual({ label: '09-15', column: 6 })
    })

    it('keeps all-missing token groups unknown while observed empty groups stay zero', () => {
        const data = series('2026-09-09T00:00:00+08:00', '2026-09-10T12:00:00+08:00', 'hour')
        Object.assign(data.points[0], {
            message_count: 1,
            failed_count: 1,
            missing_usage_count: 1,
            input_tokens: null,
            output_tokens: null,
            total_tokens: null,
        })
        const layout = buildUsageHeatmap(data)
        expect(layout.tiles[0].point?.total_tokens).toBeNull()
        expect(layout.tiles[1].point?.total_tokens).toBe(0)
    })

    it('lays out a month as one day per column and six time rows', () => {
        const data = series('2026-08-02T00:00:00+08:00', '2026-09-01T00:00:00+08:00', 'day')
        const layout = buildUsageHeatmap(data)
        expect([layout.rows, layout.columns, layout.hoursPerTile]).toEqual([6, 30, 4])
        expect(layout.tiles).toHaveLength(180)
        expect(layout.tiles[0]).toMatchObject({ row: 0, column: 0 })
        expect(layout.tiles[6]).toMatchObject({ row: 0, column: 1 })
        expect(new Set(layout.tiles.map((tile) => `${tile.row}-${tile.column}`)).size).toBe(180)
    })

    it('preserves leap day and year boundaries with a column per week', () => {
        const data = series('2024-01-01T00:00:00+08:00', '2025-01-01T00:00:00+08:00', 'day')
        const layout = buildUsageHeatmap(data)
        expect([layout.rows, layout.columns]).toEqual([7, 53])
        expect(layout.tiles).toHaveLength(366)
        expect(layout.tiles.some((tile) => tile.startAt.startsWith('2024-02-29'))).toBe(true)
        expect(layout.columnLabels.map((item) => item.label)).toHaveLength(12)
    })

    it('selects resolution by covered calendar dates and adds a 365-day preset', () => {
        const now = Date.parse('2026-09-15T13:30:00+08:00')
        expect(usageGranularity(usagePresetRange('today', now))).toBe('hour')
        expect(usageGranularity(usagePresetRange('30d', now))).toBe('hour')
        const year = usagePresetRange('year', now)
        expect(year.startAt).toBe('2025-09-16T00:00:00+08:00')
        expect(usageGranularity(year)).toBe('day')
        expect(buildUsageHeatmap(series(year.startAt, year.endAt, 'day')).tiles).toHaveLength(365)
    })
})
