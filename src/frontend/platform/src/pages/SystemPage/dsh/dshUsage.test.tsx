import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { UsageSummary } from './UsageSummary'
import type { DshUsage } from '@/types/dsh'
vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, args?: Record<string, unknown>) =>
            args ? `${key} ${JSON.stringify(args)}` : key,
    }),
}))
const usage: DshUsage = {
    month: '2026-09',
    billing_timezone: 'Asia/Shanghai',
    used: 1500,
    limit: 1000,
    remaining: 0,
    source: 'live',
    as_of: '2026-09-09T00:00:00Z',
    quota_state: 'exhausted',
    unknown_pending: 0,
    models: { '1': 1500 },
    model_limits: { '1': 1000 },
}
describe('DSH usage truthfulness', () => {
    it('shows completed overage rather than clamping actual usage to the limit', () => {
        render(
            <UsageSummary
                lastCall={null}
                lastCallSource="persisted"
                usage={usage}
                modelNames={{ '1': 'Fixture model' }}
            />,
        )
        expect(screen.getAllByText(/"used":1500/)).toHaveLength(2)
        expect(
            screen.getByText(/Fixture model:.*"used":1500.*"remaining":0/),
        ).toBeTruthy()
        expect(screen.queryByText('dsh.unknownHelp')).toBeNull()
    })
    it('labels unavailable counters explicitly and provides no force-clear action', () => {
        render(
            <UsageSummary
                lastCall={null}
                lastCallSource="persisted"
                usage={{
                    ...usage,
                    used: null,
                    remaining: null,
                    source: 'unavailable',
                    as_of: null,
                    models: null,
                    model_limits: null,
                    unknown_pending: null,
                    quota_state: 'unavailable',
                }}
                modelNames={{}}
            />,
        )
        expect(screen.getByText(/"used":"dsh.unavailable"/)).toBeTruthy()
        expect(screen.getByRole('status').textContent).toBe('dsh.unknownHelp')
        expect(screen.queryByRole('button')).toBeNull()
    })
    it('keeps the historical source label when live state is unavailable', () => {
        render(
            <UsageSummary
                lastCall={null}
                lastCallSource="persisted"
                usage={{
                    ...usage,
                    source: 'persisted',
                    quota_state: 'unavailable',
                    unknown_pending: 1,
                }}
                modelNames={{}}
            />,
        )
        expect(screen.getByText(/dsh.persisted/)).toBeTruthy()
        expect(screen.getByRole('status').textContent).toBe('dsh.unknownHelp')
    })
    it('keeps a second model available after another model overruns its independent quota', () => {
        render(
            <UsageSummary
                lastCall={null}
                lastCallSource="persisted"
                modelNames={{ '1': 'Overrun model', '2': 'Available model' }}
                usage={{
                    ...usage,
                    limit: 1200,
                    remaining: 0,
                    models: { '1': 1500, '2': 0 },
                    model_limits: { '1': 1000, '2': 200 },
                }}
            />,
        )
        expect(screen.getByText(/^dsh.usageSummary/).textContent).toContain(
            '"remaining":200',
        )
        expect(screen.getByText(/Overrun model:/).textContent).toContain(
            '"remaining":0',
        )
        expect(screen.getByText(/Available model:/).textContent).toContain(
            '"used":0,"limit":200,"remaining":200',
        )
    })
    it('retains usage for removed models without treating it as another model quota', () => {
        render(
            <UsageSummary
                lastCall={null}
                lastCallSource="persisted"
                modelNames={{ '1': 'Removed' }}
                usage={{
                    ...usage,
                    models: { '1': 1500, '2': 0 },
                    model_limits: { '2': 200 },
                }}
            />,
        )
        expect(screen.getByText(/Removed:/).textContent).toContain(
            '"limit":"dsh.notConfigured"',
        )
        expect(screen.getByText(/^dsh.usageSummary/).textContent).toContain(
            '"remaining":200',
        )
    })
    it('does not fabricate zero usage or remaining quota when a configured model counter is missing', () => {
        render(
            <UsageSummary
                lastCall={null}
                lastCallSource="persisted"
                modelNames={{ '1': 'Known model', '2': 'Missing counter' }}
                usage={{
                    ...usage,
                    models: { '1': 0 },
                    model_limits: { '1': 1000, '2': 200 },
                }}
            />,
        )
        expect(screen.getByText(/^dsh.usageSummary/).textContent).toContain(
            '"remaining":"dsh.unavailable"',
        )
        expect(screen.getByText(/Missing counter:/).textContent).toContain(
            '"used":"dsh.unavailable","limit":200,"remaining":"dsh.unavailable"',
        )
        expect(screen.getByText(/Known model:/).textContent).toContain(
            '"used":0,"limit":1000,"remaining":1000',
        )
    })
})
