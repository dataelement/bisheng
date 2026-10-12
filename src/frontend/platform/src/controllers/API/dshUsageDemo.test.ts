import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DshUsageOverviewPage, DshUsageTimeSummary } from '@/types/dsh'
import { addDemoSummary, demoUsageMetrics, usageDemoConfig, type UsageDemoConfig } from './dshUsageDemo'
import { getDshUsageHistoryOverview, getDshUsageHistorySummary } from './dshUsageHistory'
import { getDshUsagePresentationOverview, getDshUsagePresentationSummary } from './dshUsagePresentation'
import { buildUsageHeatmap } from '@/pages/SystemPage/dsh/usageHeatmapData'
import { messageHeatLevel, usageHeatLevel } from '@/pages/SystemPage/dsh/usageHeatScale'

vi.mock('./dshUsageHistory', () => ({
    getDshUsageHistoryOverview: vi.fn(),
    getDshUsageHistorySummary: vi.fn(),
}))
const config: UsageDemoConfig = {
    origin: 'http://localhost:3000',
    tenantId: 1,
    userId: 1,
    userName: 'admin',
    start: '2024-09-16',
    before: '2026-09-15',
}
const today = '2026-09-15T00:00:00+08:00'
const tomorrow = '2026-09-16T00:00:00+08:00'
const start = '2026-09-14T00:00:00+08:00'
const empty = demoUsageMetrics(today, tomorrow, config)
const real = {
    ...empty,
    input_tokens: 100,
    output_tokens: 10,
    total_tokens: 110,
    message_count: 1,
    qa_count: 1,
    recorded_usage_count: 1,
}
const summary: DshUsageTimeSummary = {
    start_at: start,
    end_at: tomorrow,
    timezone: 'Asia/Shanghai',
    granularity: 'day',
    totals: real,
    points: [
        { ...empty, start_at: start, end_at: today },
        { ...real, start_at: today, end_at: tomorrow },
    ],
}
const page: DshUsageOverviewPage = {
    tenant_id: 1,
    department_id: null,
    start_at: start,
    end_at: tomorrow,
    timezone: 'Asia/Shanghai',
    totals: real,
    summary,
    items: [{ user_id: 1, user_name: 'admin', department_id: 2, department_name: 'Visitors', metrics: real }],
    next_cursor: null,
    has_more: false,
}
const query = { startAt: start, endAt: tomorrow, limit: 20, includeSummary: true }
beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-09-15T18:00:00+08:00'))
    vi.stubEnv('VITE_DSH_USAGE_DEMO', JSON.stringify({ ...config, origin: window.location.origin }))
    vi.mocked(getDshUsageHistoryOverview).mockResolvedValue(page)
    vi.mocked(getDshUsageHistorySummary).mockResolvedValue(summary)
})
afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
})

describe('isolated historical demo usage', () => {
    it('requires explicit valid deployment config, exact origin and a historical cutoff', () => {
        const raw = JSON.stringify(config)
        expect(usageDemoConfig(raw, config.origin)).toEqual(config)
        expect(usageDemoConfig('', config.origin)).toBeNull()
        expect(usageDemoConfig(raw, 'http://another-tenant')).toBeNull()
        expect(usageDemoConfig('{', config.origin)).toBeNull()
        expect(usageDemoConfig(JSON.stringify({ ...config, before: '2026-09-16' }), config.origin)).toBeNull()
        expect(usageDemoConfig(JSON.stringify({ ...config, tenantId: 0 }), config.origin)).toBeNull()
    })
    it('keeps today and every later date real, even when revisiting tomorrow', () => {
        expect(empty.message_count).toBe(0)
        expect(demoUsageMetrics(today, '2026-09-30T00:00:00+08:00', config)).toEqual(empty)
        expect(
            addDemoSummary({ ...summary, start_at: today, points: [summary.points[1]] }, config).totals,
        ).toEqual(real)
    })
    it('produces deterministic varied hourly data that sums exactly to the daily total', () => {
        const daily = demoUsageMetrics(start, today, config)
        const hourly = Array.from({ length: 24 }, (_, hour) =>
            demoUsageMetrics(
                new Date(Date.parse(start) + hour * 3600000).toISOString(),
                new Date(Date.parse(start) + (hour + 1) * 3600000).toISOString(),
                config,
            ),
        )
        expect(daily).toEqual(demoUsageMetrics(start, today, config))
        expect(hourly.filter((value) => value.message_count > 0).length).toBeGreaterThanOrEqual(2)
        expect(hourly.reduce((sum, value) => sum + value.total_tokens!, 0)).toBe(daily.total_tokens)
        expect(daily.total_tokens).toBe(daily.input_tokens! + daily.output_tokens!)
    })
    it('distributes the historical fixture across neutral zero and all five daily bands', () => {
        const levels: number[] = []
        const messageLevels: number[] = []
        const dailyTotals: number[] = []
        for (
            let day = Date.parse(`${config.start}T00:00:00+08:00`);
            day < Date.parse(`${config.before}T00:00:00+08:00`);
            day += 86400000
        ) {
            const metrics = demoUsageMetrics(
                new Date(day).toISOString(),
                new Date(day + 86400000).toISOString(),
                config,
            )
            const tokens = metrics.total_tokens!
            dailyTotals.push(tokens)
            levels.push(usageHeatLevel(tokens, 'day'))
            messageLevels.push(messageHeatLevel(metrics.message_count, 'day'))
        }
        expect([...new Set(levels)].sort()).toEqual([0, 1, 2, 3, 4, 5])
        expect(levels.filter((level) => level >= 4).length / levels.length).toBeLessThan(0.05)
        expect(levels.filter((level) => level <= 1).length / levels.length).toBeGreaterThan(0.75)
        expect(messageLevels.filter((level) => level >= 4).length / messageLevels.length).toBeLessThan(0.01)
        expect(messageLevels.filter((level) => level <= 1).length / messageLevels.length).toBeGreaterThan(0.85)
        const weeklyMatches = dailyTotals.slice(7).filter((tokens, index) => tokens === dailyTotals[index]).length
        expect(weeklyMatches / (dailyTotals.length - 7)).toBeLessThan(0.2)
    })
    it('supports partial-hour ranges without duplicate events across boundaries', () => {
        const middle = '2026-09-14T12:17:00+08:00'
        const left = demoUsageMetrics(start, middle, config)
        const right = demoUsageMetrics(middle, today, config)
        expect(left.total_tokens! + right.total_tokens!).toBe(
            demoUsageMetrics(start, today, config).total_tokens,
        )
    })
    it('preserves the input data, sums card totals and retains demo provenance through heatmap grouping', () => {
        const snapshot = structuredClone(summary)
        const result = addDemoSummary(summary, config)
        expect(summary).toEqual(snapshot)
        expect(result.points[1]).toBe(summary.points[1])
        expect(result.totals.total_tokens).toBe(
            result.points.reduce((sum, point) => sum + point.total_tokens!, 0),
        )
        expect(result.demo?.total_tokens).toBe(result.points[0].demo_tokens)
        expect(buildUsageHeatmap(result).tiles.some((tile) => tile.point?.demo_tokens)).toBe(true)
    })
    it('leaves missing real usage visible while adding recorded demo values', () => {
        const missing = {
            ...empty,
            total_tokens: null,
            input_tokens: null,
            output_tokens: null,
            message_count: 1,
            missing_usage_count: 1,
            usage_unknown_count: 1,
        }
        const result = addDemoSummary(
            { ...summary, totals: missing, points: [{ ...missing, start_at: start, end_at: today }] },
            config,
        )
        expect(result.totals.missing_usage_count).toBe(1)
        expect(result.totals.total_tokens).toBeGreaterThan(0)
    })
    it('counts admin exactly once in tenant totals and member details', async () => {
        const result = await getDshUsagePresentationOverview(query)
        expect(result.totals.total_tokens).toBe(result.items[0].metrics.total_tokens)
        expect(result.summary?.totals.total_tokens).toBe(result.totals.total_tokens)
        expect((await getDshUsagePresentationSummary('1', query)).totals).toEqual(result.totals)
    })
    it('keeps other tenants, users and departments real', async () => {
        vi.mocked(getDshUsageHistoryOverview).mockResolvedValueOnce({ ...page, tenant_id: 2 })
        expect((await getDshUsagePresentationOverview(query)).totals).toEqual(real)
        vi.mocked(getDshUsageHistoryOverview).mockResolvedValueOnce({ ...page, items: [], department_id: 99 })
        expect((await getDshUsagePresentationOverview({ ...query, departmentId: 99 })).totals).toEqual(real)
        expect(await getDshUsagePresentationSummary('2', query)).toBe(summary)
    })
    it('preserves API totals and department filters in the production presentation', async () => {
        expect((await getDshUsagePresentationOverview({ ...query, keyword: 'bob' })).totals).toEqual(real)
        vi.mocked(getDshUsageHistoryOverview).mockResolvedValueOnce({
            ...page,
            items: [],
            next_cursor: 'more',
            has_more: true,
        })
        const result = await getDshUsagePresentationOverview({ ...query, departmentId: 2 })
        expect(result.totals).toEqual(real)
        expect(getDshUsageHistoryOverview).toHaveBeenLastCalledWith(
            expect.objectContaining({ departmentId: 2 }),
        )
        expect(getDshUsageHistoryOverview).toHaveBeenCalledTimes(2)
    })
    it('propagates real API failures and abort signals', async () => {
        const signal = new AbortController().signal
        vi.mocked(getDshUsageHistoryOverview).mockRejectedValueOnce(new Error('unavailable'))
        await expect(getDshUsagePresentationOverview(query, signal)).rejects.toThrow('unavailable')
        expect(getDshUsageHistoryOverview).toHaveBeenCalledWith(query, signal)
    })
})
