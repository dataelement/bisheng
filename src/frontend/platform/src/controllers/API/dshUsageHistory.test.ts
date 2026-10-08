import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DshUsageMetrics, DshUsageOverviewPage, DshUsageTimeSummary } from '@/types/dsh'
import { getDshUsageOverview, getDshUsageTimeSummary } from './dsh'
import {
    getDshUsageHistoryOverview,
    getDshUsageHistorySummary,
    splitUsageHistoryRange,
    splitUsageHourlyRange,
    sumUsageMetrics,
} from './dshUsageHistory'

vi.mock('./dsh', () => ({ getDshUsageOverview: vi.fn(), getDshUsageTimeSummary: vi.fn() }))

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
const recorded = {
    ...empty,
    message_count: 1,
    qa_count: 1,
    recorded_usage_count: 1,
    input_tokens: 10,
    output_tokens: 5,
    total_tokens: 15,
}
const unknown = {
    ...empty,
    message_count: 1,
    failed_count: 1,
    missing_usage_count: 1,
    usage_unknown_count: 1,
    input_tokens: null,
    output_tokens: null,
    total_tokens: null,
}
const range = { startAt: '2024-09-23T00:00:00+08:00', endAt: '2026-09-15T16:46:00+08:00' }
const segments = splitUsageHistoryRange(range)
const summaries: DshUsageTimeSummary[] = segments.map((segment, index) => ({
    start_at: segment.startAt,
    end_at: segment.endAt,
    timezone: 'Asia/Shanghai',
    granularity: 'day',
    totals: index ? recorded : empty,
    points: [{ ...(index ? recorded : empty), start_at: segment.startAt, end_at: segment.endAt }],
}))
const pages: DshUsageOverviewPage[] = summaries.map((summary) => ({
    tenant_id: 1,
    department_id: null,
    start_at: summary.start_at,
    end_at: summary.end_at,
    timezone: summary.timezone,
    totals: summary.totals,
    summary,
    items: [
        {
            user_id: 1,
            user_name: 'admin',
            department_id: 2,
            department_name: 'Visitors',
            metrics: summary.totals,
        },
    ],
    next_cursor: null,
    has_more: false,
}))

beforeEach(() => vi.resetAllMocks())

describe('extended usage history', () => {
    it('splits at a shared exclusive boundary and respects the existing 366-day API limit', () => {
        expect(segments).toHaveLength(2)
        expect(segments[0].endAt).toBe(segments[1].startAt)
        expect(segments[0].startAt).toBe(range.startAt)
        expect(segments[1].endAt).toBe(range.endAt)
        segments.forEach((segment) =>
            expect(Date.parse(segment.endAt) - Date.parse(segment.startAt)).toBeLessThanOrEqual(
                366 * 86400000,
            ),
        )
        expect(splitUsageHistoryRange(segments[0])).toEqual([segments[0]])
        for (const invalid of [
            { ...range, startAt: 'invalid' },
            { ...range, endAt: range.startAt },
            { ...range, startAt: '2020-01-01' },
        ]) {
            expect(() => splitUsageHistoryRange(invalid)).toThrow('Invalid usage history range')
        }
    })
    it('preserves unknown token usage while adding known values and request counts', () => {
        expect(sumUsageMetrics([empty, unknown])).toMatchObject({
            total_tokens: null,
            message_count: 1,
            missing_usage_count: 1,
        })
        expect(sumUsageMetrics([recorded, unknown])).toMatchObject({
            total_tokens: 15,
            message_count: 2,
            missing_usage_count: 1,
        })
        expect(() => sumUsageMetrics([])).toThrow()
    })
    it('keeps the single-range request and abort signal unchanged', async () => {
        const signal = new AbortController().signal
        vi.mocked(getDshUsageTimeSummary).mockResolvedValue(summaries[0])
        expect(await getDshUsageHistorySummary('1', segments[0], signal)).toBe(summaries[0])
        expect(getDshUsageTimeSummary).toHaveBeenCalledExactlyOnceWith('1', segments[0], signal)
    })
    it('combines daily results without counting a boundary twice', async () => {
        const signal = new AbortController().signal
        vi.mocked(getDshUsageTimeSummary)
            .mockResolvedValueOnce(summaries[0])
            .mockResolvedValueOnce(summaries[1])
        const result = await getDshUsageHistorySummary('1', range, signal)
        expect(result).toMatchObject({
            start_at: range.startAt,
            end_at: range.endAt,
            totals: recorded,
            points: summaries.flatMap((part) => part.points),
        })
        segments.forEach((segment, index) =>
            expect(getDshUsageTimeSummary).toHaveBeenNthCalledWith(
                index + 1,
                '1',
                { ...segment, granularity: 'day' },
                signal,
            ),
        )
    })
    it('fails the complete view when either range fails or is cancelled', async () => {
        vi.mocked(getDshUsageTimeSummary)
            .mockResolvedValueOnce(summaries[0])
            .mockRejectedValueOnce(new DOMException('Aborted', 'AbortError'))
        await expect(getDshUsageHistorySummary('1', range)).rejects.toMatchObject({ name: 'AbortError' })
    })
    it('splits hourly history into requests accepted by the seven-day API contract', async () => {
        const month = {
            startAt: '2026-08-18T00:00:00+08:00',
            endAt: '2026-09-16T15:12:00+08:00',
            granularity: 'hour' as const,
        }
        const hourlySegments = splitUsageHourlyRange(month)
        expect(hourlySegments).toHaveLength(5)
        hourlySegments.forEach((segment, index) => {
            expect(Date.parse(segment.endAt) - Date.parse(segment.startAt)).toBeLessThanOrEqual(
                7 * 86400000,
            )
            if (index) expect(segment.startAt).toBe(hourlySegments[index - 1].endAt)
        })
        const hourlySummaries = hourlySegments.map((segment) => ({
            ...summaries[0],
            start_at: segment.startAt,
            end_at: segment.endAt,
            granularity: 'hour' as const,
            points: [{ ...empty, start_at: segment.startAt, end_at: segment.endAt }],
        }))
        hourlySummaries.forEach((summary) =>
            vi.mocked(getDshUsageTimeSummary).mockResolvedValueOnce(summary),
        )
        const result = await getDshUsageHistorySummary('1', month)
        expect(result.start_at).toBe(month.startAt)
        expect(result.end_at).toBe(month.endAt)
        expect(result.points).toHaveLength(5)
        hourlySegments.forEach((segment, index) =>
            expect(getDshUsageTimeSummary).toHaveBeenNthCalledWith(
                index + 1,
                '1',
                { ...segment, granularity: 'hour' },
                undefined,
            ),
        )
    })
    it('merges a stable member page and optional department summary', async () => {
        vi.mocked(getDshUsageOverview).mockResolvedValueOnce(pages[0]).mockResolvedValueOnce(pages[1])
        const result = await getDshUsageHistoryOverview({ ...range, includeSummary: true, limit: 20 })
        expect(result.totals).toEqual(recorded)
        expect(result.items[0].metrics).toEqual(recorded)
        expect(result.summary?.totals).toEqual(recorded)
        expect(result.end_at).toBe(range.endAt)
    })
    it.each([
        { tenant_id: 2 },
        { next_cursor: 'changed' },
        { has_more: true },
        { department_id: 3 },
        { items: [] },
        { items: [{ ...pages[1].items[0], department_id: 3 }] },
    ])('requires a refresh for changing tenant membership or pagination: %j', async (change) => {
        vi.mocked(getDshUsageOverview)
            .mockResolvedValueOnce(pages[0])
            .mockResolvedValueOnce({ ...pages[1], ...change })
        await expect(getDshUsageHistoryOverview({ ...range, limit: 20 })).rejects.toThrow(
            'membership changed',
        )
    })
    it('requires all requested summary segments', async () => {
        vi.mocked(getDshUsageOverview)
            .mockResolvedValueOnce(pages[0])
            .mockResolvedValueOnce({ ...pages[1], summary: null })
        await expect(
            getDshUsageHistoryOverview({ ...range, limit: 20, includeSummary: true }),
        ).rejects.toThrow('summary is required')
    })
})
