import { fireEvent, render, screen, within } from '@testing-library/react'
import { createInstance } from 'i18next'
import { I18nextProvider } from 'react-i18next'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import zh from '../../../../public/locales/zh-Hans/bs.json'
import type { DshUsageMetrics, DshUsageTimeSummary } from '@/types/dsh'
import { UsageHeatmap } from './UsageHeatmap'
import fixtures from './usageTokenFormat.fixtures.json'

vi.unmock('react-i18next')
const i18n = createInstance()
beforeAll(async () => {
    await i18n.init({
        lng: 'zh-Hans',
        resources: { 'zh-Hans': { translation: zh } },
        interpolation: { escapeValue: false },
    })
})
const metrics: DshUsageMetrics = {
    message_count: 36,
    qa_count: 36,
    failed_count: 0,
    cancelled_count: 0,
    running_count: 0,
    usage_unknown_count: 0,
    recorded_usage_count: 36,
    missing_usage_count: 0,
    input_tokens: 3129252,
    output_tokens: 58600,
    total_tokens: 3187852,
}
function renderHeatmap(
    overrides: Partial<DshUsageMetrics> = {},
    hourly = false,
    outlierTokens?: number,
    metric: 'tokens' | 'messages' = 'tokens',
) {
    const point = { ...metrics, ...overrides }
    const summary: DshUsageTimeSummary = {
        start_at: '2026-09-01T00:00:00+08:00',
        end_at: hourly ? '2026-09-01T02:30:00+08:00' : '2026-10-15T00:00:00+08:00',
        timezone: 'Asia/Shanghai',
        granularity: hourly ? 'hour' : 'day',
        totals: point,
        points: [
            {
                ...point,
                start_at: '2026-08-31T16:00:00Z',
                end_at: hourly ? '2026-09-01T01:00:00+08:00' : '2026-09-02T00:00:00+08:00',
            },
        ],
    }
    if (outlierTokens !== undefined) {
        summary.points.push({
            ...metrics,
            input_tokens: outlierTokens,
            output_tokens: 0,
            total_tokens: outlierTokens,
            start_at: '2026-09-02T00:00:00+08:00',
            end_at: '2026-09-03T00:00:00+08:00',
        })
    }
    return render(
        <I18nextProvider i18n={i18n}>
            <UsageHeatmap summary={summary} metric={metric} />
        </I18nextProvider>,
    )
}

describe('heatmap daily Token tooltip', () => {
    it('aligns start, noon and end labels to the heatmap bounds and center', () => {
        renderHeatmap({}, true)
        for (const [hour, position, offset] of [[0, '0%', '0%'], [12, '50%', '-50%'], [24, '100%', '-100%']] as const) {
            const label = screen.getByText(`${String(hour).padStart(2, '0')}:00`)
            expect(label.style.top).toBe(position)
            expect(label.style.transform).toBe(`translateY(${offset})`)
        }
        expect(screen.getByRole('list')).toHaveAttribute('data-rows', '6')
    })

    it.each([undefined, 1_200_000_000])('keeps a daily tile in its fixed band with outlier %s', (outlier) => {
        renderHeatmap({}, false, outlier)
        expect(screen.getAllByRole('button')[0]).toHaveAttribute('data-heat-level', '1')
    })

    it('uses equal intervals for four-hour month tiles', () => {
        renderHeatmap({ input_tokens: 60_000_000, output_tokens: 0, total_tokens: 60_000_000 }, true)
        expect(screen.getAllByRole('button')[0]).toHaveAttribute('data-heat-level', '3')
    })

    it('opens on a mouse hover', async () => {
        renderHeatmap()
        const tile = screen.getAllByRole('button')[0]
        fireEvent.pointerEnter(tile, { pointerType: 'mouse' })
        expect(await screen.findByRole('tooltip')).toHaveTextContent(
            i18n.t('dsh.heatmapTokenValue', { exact: fixtures[4].compact }),
        )
    })

    it('updates one persistent tooltip while crossing directly between adjacent tiles', async () => {
        renderHeatmap({}, false, 1_200_000_000)
        const [first, second] = screen.getAllByRole('button')
        fireEvent.pointerEnter(first, { pointerType: 'mouse' })
        const tooltip = await screen.findByRole('tooltip')
        expect(tooltip).toHaveTextContent('2026-09-01')

        fireEvent.pointerEnter(second, { pointerType: 'mouse', relatedTarget: first })
        expect(screen.getByRole('tooltip')).toBe(tooltip)
        expect(tooltip).toHaveTextContent('2026-09-02')
        expect(screen.getAllByRole('tooltip')).toHaveLength(1)
        expect(tooltip).toHaveClass('pointer-events-none')
        expect(second).toHaveAttribute('aria-describedby', tooltip.id)

        fireEvent.pointerLeave(screen.getByRole('list', { name: zh.dsh.tokenActivity }))
        expect(screen.queryByRole('tooltip')).toBeNull()
    })

    it('removes footer prose and shows the Beijing date and compact total on focus', async () => {
        const { container } = renderHeatmap()
        expect(screen.queryByText(zh.dsh.heatmapDailyGranularity)).toBeNull()
        expect(screen.queryByText(zh.dsh.beijingTime)).toBeNull()
        expect(screen.queryByText(zh.dsh.heatmapLess)).toBeNull()
        expect(screen.queryByText(zh.dsh.heatmapMore)).toBeNull()
        fireEvent.focus(screen.getAllByRole('button')[0])
        const tooltip = await screen.findByRole('tooltip')
        expect(tooltip).toHaveTextContent('2026-09-01')
        expect(tooltip).toHaveTextContent(i18n.t('dsh.heatmapTokenValue', { exact: fixtures[4].compact }))
        expect(tooltip).not.toHaveTextContent(fixtures[4].exact)
        expect(tooltip).not.toHaveTextContent('2026-09-02')
        expect(container.contains(tooltip)).toBe(false)
        fireEvent.keyDown(screen.getAllByRole('button')[0], { key: 'Escape' })
        expect(screen.queryByRole('tooltip')).toBeNull()
    })

    it('keeps the exact time interval for month tiles', async () => {
        renderHeatmap({}, true)
        fireEvent.focus(screen.getAllByRole('button')[0])
        const tooltip = await screen.findByRole('tooltip')
        expect(tooltip).toHaveTextContent('2026-09-01 00:00 – 2026-09-01 04:00')
    })

    it('shows an observed zero once, with no redundant abbreviation', async () => {
        renderHeatmap({ input_tokens: 0, output_tokens: 0, total_tokens: 0 })
        fireEvent.focus(screen.getAllByRole('button')[0])
        const tooltip = await screen.findByRole('tooltip')
        expect(within(tooltip).getByText('0 Token')).toBeTruthy()
        expect(tooltip.textContent).not.toContain('（0）')
    })

    it('preserves unknown amounts and explains incomplete records', async () => {
        renderHeatmap({
            input_tokens: null,
            output_tokens: null,
            total_tokens: null,
            recorded_usage_count: 0,
            missing_usage_count: 36,
        })
        fireEvent.focus(screen.getAllByRole('button')[0])
        const tooltip = await screen.findByRole('tooltip')
        expect(tooltip).toHaveTextContent(`${zh.dsh.unavailable} Token`)
        expect(tooltip).toHaveTextContent(i18n.t('dsh.missingUsageCount', { count: 36 }))
        expect(within(tooltip).queryByText('0 Token')).toBeNull()
    })

    it('keeps future hours distinct from observed usage', async () => {
        renderHeatmap({}, true)
        fireEvent.focus(screen.getAllByRole('button')[5])
        const tooltip = await screen.findByRole('tooltip')
        expect(tooltip).toHaveTextContent(zh.dsh.heatmapFuture)
        expect(tooltip).not.toHaveTextContent('Token')
    })
})

describe('heatmap message tooltip', () => {
    it('reuses the calendar layout and displays message counts with a fixed five-level scale', async () => {
        renderHeatmap({ message_count: 12 }, false, 1_200_000_000, 'messages')
        const grid = screen.getByRole('list', { name: zh.dsh.messageActivity })
        const [first, second] = screen.getAllByRole('button')

        expect(grid).toHaveAttribute('data-heatmap-metric', 'messages')
        expect(first).toHaveAttribute('data-heat-level', '2')
        expect(second).toHaveAttribute('data-heat-level', '5')

        fireEvent.pointerEnter(first, { pointerType: 'mouse' })
        const tooltip = await screen.findByRole('tooltip')
        expect(tooltip).toHaveTextContent(i18n.t('dsh.heatmapMessageValue', { value: '12' }))
        expect(tooltip).not.toHaveTextContent('Token')
    })

    it('keeps zero-message tiles neutral', () => {
        renderHeatmap({ message_count: 0 }, false, undefined, 'messages')
        expect(screen.getAllByRole('button')[0]).toHaveAttribute('data-heat-level', '0')
    })
})
