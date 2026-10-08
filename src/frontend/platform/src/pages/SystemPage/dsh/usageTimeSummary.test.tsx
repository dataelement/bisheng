import zh from '../../../../public/locales/zh-Hans/bs.json'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DshUsageTimeSummary } from '@/types/dsh'
import { UsageHeatmap } from './UsageHeatmap'
import { usageHeatLevel } from './usageHeatScale'
import { usagePresetRange } from './usageRange'
import { UsageSummaryView } from './UsageSummaryView'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        i18n: { language: 'zh-Hans' },
        t: (key: string, args?: Record<string, unknown>) =>
            args ? `${key} ${JSON.stringify(args)}` : key,
    }),
}))

const empty = {
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
const summary: DshUsageTimeSummary = {
    start_at: '2026-09-15T00:00:00+08:00',
    end_at: '2026-09-15T02:30:00+08:00',
    timezone: 'Asia/Shanghai',
    granularity: 'hour',
    totals: empty,
    points: [0, 1, 2].map((hour) => ({
        ...empty,
        start_at: `2026-09-15T0${hour}:00:00+08:00`,
        end_at: `2026-09-15T0${hour === 2 ? '2:30' : `${hour + 1}:00`}:00+08:00`,
    })),
}

describe('usage calendar contracts', () => {
    it('uses today, one month and one year ranges in Beijing time', () => {
        const now = Date.parse('2026-09-15T02:30:00+08:00')
        expect(usagePresetRange('today', now)).toEqual({
            startAt: '2026-09-15T00:00:00+08:00',
            endAt: '2026-09-15T02:30:00+08:00',
        })
        expect(usagePresetRange('30d', now).startAt).toBe(
            '2026-08-17T00:00:00+08:00',
        )
        expect(usagePresetRange('year', now).startAt).toBe(
            '2025-09-16T00:00:00+08:00',
        )
    })
    it('renders today as one non-animated line chart and switches its metric in place', () => {
        render(<UsageSummaryView summary={summary} />)
        expect(
            document.querySelectorAll('[data-usage-line-chart="tokens"]'),
        ).toHaveLength(1)
        expect(
            document.querySelectorAll('[data-usage-calendar-card]'),
        ).toHaveLength(1)
        fireEvent.click(
            screen.getByRole('button', { name: 'dsh.messageCount' }),
        )
        expect(
            document.querySelectorAll('[data-usage-line-chart="messages"]'),
        ).toHaveLength(1)
    })
    it('renders one month as dated columns and six four-hour rows', () => {
        const monthly = { ...summary, start_at: '2026-08-17T00:00:00+08:00' }
        render(<UsageHeatmap summary={monthly} />)
        const grid = screen.getByRole('list')
        expect(grid.getAttribute('data-rows')).toBe('6')
        expect(grid.getAttribute('data-columns')).toBe('30')
        const tiles = screen.getAllByRole('button')
        expect(tiles).toHaveLength(180)
        expect(tiles[174].getAttribute('aria-label')).toContain(
            '2026-09-15 00:00',
        )
        expect(tiles[175].getAttribute('data-future')).toBe('true')
        expect(tiles[174].style.width).toBe('12px')
        expect(tiles[174].style.height).toBe('12px')
        expect(grid.style.gap).toBe('3px')
        expect(screen.getByText(/08-17/)).toBeTruthy()
        expect(screen.getByText(/09-15/)).toBeTruthy()
    })
    it('keeps partial missing usage visible beside recorded tokens', () => {
        const metrics = {
            ...empty,
            message_count: 2,
            qa_count: 1,
            failed_count: 1,
            recorded_usage_count: 1,
            missing_usage_count: 1,
            input_tokens: 10,
            output_tokens: 5,
            total_tokens: 15,
        }
        const partial = {
            ...summary,
            start_at: '2026-08-17T00:00:00+08:00',
            totals: metrics,
            points: [{ ...summary.points[0], ...metrics }],
        }
        render(<UsageSummaryView summary={partial} />)
        expect(screen.getByRole('status').textContent).toContain(
            'dsh.missingUsageCount',
        )
        const unknown = screen
            .getAllByRole('button')
            .find((button) => button.dataset.usageUnknown === 'true')!
        expect(unknown).toBeTruthy()
        expect(
            unknown
                .querySelector('[aria-hidden="true"]')
                ?.classList.contains('bg-amber-500'),
        ).toBe(true)
        expect(usageHeatLevel(15, 'hour')).toBe(1)
        expect(usageHeatLevel(null, 'hour')).toBe(0)
    })
    it('switches Token and message data in one calendar', () => {
        render(
            <UsageSummaryView
                summary={{ ...summary, start_at: '2026-08-17T00:00:00+08:00' }}
            />,
        )
        const tokenGrid = screen.getByRole('list', {
            name: 'dsh.tokenActivity',
        })
        expect(tokenGrid).toHaveAttribute('data-heatmap-metric', 'tokens')
        fireEvent.click(
            screen.getByRole('button', { name: 'dsh.messageCount' }),
        )
        const messageGrid = screen.getByRole('list', {
            name: 'dsh.messageActivity',
        })
        expect(messageGrid).toHaveAttribute('data-heatmap-metric', 'messages')
        expect(messageGrid.getAttribute('data-rows')).toBe(
            tokenGrid.getAttribute('data-rows'),
        )
        expect(messageGrid.getAttribute('data-columns')).toBe(
            tokenGrid.getAttribute('data-columns'),
        )
        expect(
            document.querySelectorAll('[data-usage-calendar-card]'),
        ).toHaveLength(1)
        expect(document.querySelector('[data-usage-totals]')).toHaveAttribute(
            'data-metric',
            'messages',
        )
        expect(
            document.querySelector('[data-usage-totals]'),
        ).not.toHaveTextContent('dsh.tokenBreakdown')
    })
    it('keeps only Token usage and message count in the summary cards', () => {
        render(
            <UsageSummaryView
                summary={{
                    ...summary,
                    totals: {
                        ...empty,
                        input_tokens: 7_336_120_183,
                        output_tokens: 1_000_001_461,
                        total_tokens: 8_336_121_644,
                    },
                }}
            />,
        )

        expect(screen.getAllByText('dsh.tokenUsage').length).toBeGreaterThan(0)
        expect(screen.getAllByText('dsh.messageCount').length).toBeGreaterThan(
            0,
        )
        expect(document.querySelector('[data-usage-totals]')).toHaveTextContent(
            `83.36${zh.dsh.tokenUnits.hundredMillion}`,
        )
        expect(
            document.querySelector('[data-usage-totals] dd'),
        ).toHaveAttribute('title', '8,336,121,644')
        expect(document.querySelector('[data-usage-totals]')).toHaveTextContent(
            `73.36${zh.dsh.tokenUnits.hundredMillion}`,
        )
        expect(screen.queryByText('dsh.qaCount')).toBeNull()
        expect(screen.queryByText('dsh.failedCount')).toBeNull()
    })
    it('renders the annual weekday grid with compact localized month labels', () => {
        const start = Date.parse('2025-09-16T00:00:00+08:00')
        const year = {
            ...summary,
            start_at: '2025-09-16T00:00:00+08:00',
            end_at: '2026-09-16T00:00:00+08:00',
            granularity: 'day' as const,
            points: Array.from({ length: 365 }, (_, day) => ({
                ...empty,
                start_at: new Date(start + day * 86400000).toISOString(),
                end_at: new Date(start + (day + 1) * 86400000).toISOString(),
            })),
        }
        render(<UsageHeatmap summary={year} />)
        const grid = screen.getByRole('list')
        expect(grid.getAttribute('data-rows')).toBe('7')
        expect(grid.getAttribute('data-columns')).toBe('53')
        expect(screen.getAllByRole('button')).toHaveLength(365)
        expect(screen.getByText('2025')).toBeTruthy()
        expect(screen.getByText('2026')).toBeTruthy()
        expect(
            screen.getByText(
                new Intl.DateTimeFormat('zh-Hans', { month: 'short' }).format(
                    new Date('2026-09-01'),
                ),
            ),
        ).toBeTruthy()
        expect(screen.getByTitle('2025-09').style.gridRow).toBe('1')
        expect(grid.style.gridTemplateColumns).toBe('repeat(53, 12px)')
        expect(grid.style.gridTemplateRows).toBe('repeat(7, 12px)')
        expect(grid.style.gap).toBe('3px')
        expect(grid.parentElement!.style.gridTemplateColumns).toBe('792px')
        expect(screen.queryByText(new Intl.DateTimeFormat('zh-Hans', { weekday: 'narrow' }).format(new Date('2026-09-14T12:00:00+08:00')))).toBeNull()
        expect(screen.queryByText(new Intl.DateTimeFormat('zh-Hans', { weekday: 'narrow' }).format(new Date('2026-09-16T12:00:00+08:00')))).toBeNull()
        expect(screen.queryByText(new Intl.DateTimeFormat('zh-Hans', { weekday: 'narrow' }).format(new Date('2026-09-18T12:00:00+08:00')))).toBeNull()
    })
})
