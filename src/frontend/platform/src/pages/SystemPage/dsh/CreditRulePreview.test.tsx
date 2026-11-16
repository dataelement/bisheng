import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { getUserCredits, type MonthCredits } from '@/controllers/API/modelPricing'
import { CreditRulePreview } from './CreditRulePreview'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, values?: Record<string, string>) => (values ? `${key} ${JSON.stringify(values)}` : key),
        i18n: { language: 'en-US' },
    }),
}))
vi.mock('@/controllers/API/modelPricing', () => ({ getUserCredits: vi.fn() }))

const month = (overrides: Partial<MonthCredits> = {}): MonthCredits => ({
    month: '2026-11', billing_timezone: 'Asia/Shanghai', reset_at: '2026-11-30T16:00:00Z',
    limit: '1000', used: '480', remaining: '520', unlimited: false, ...overrides,
})
beforeEach(() => { vi.mocked(getUserCredits).mockReset().mockResolvedValue(month()) })

it('previews the balance the member will have with the typed allowance', async () => {
    render(<CreditRulePreview userId={2} credits="1000" enabled />)
    const status = await screen.findByRole('status')
    expect(getUserCredits).toHaveBeenCalledWith(2, expect.any(AbortSignal), { monthly_credits: '1000', enabled: true })
    expect(status).toHaveTextContent('dsh.unified.previewBalance {"used":"480","remaining":"520","limit":"1,000"}')
    expect(status).not.toHaveTextContent('previewOverdrawn')
    expect(status).not.toHaveTextContent('previewHigherRule')
})

it('tells how much an overdrawn member needs before they can continue', async () => {
    vi.mocked(getUserCredits).mockResolvedValue(month({ used: '1284.754515', remaining: '0' }))
    render(<CreditRulePreview userId={2} credits="1000" enabled />)
    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('dsh.unified.previewOverdrawn {"used":"1,284.75"}')
    expect(status.className).toContain('text-amber-600')
})

it('names the higher department or role allowance that wins', async () => {
    vi.mocked(getUserCredits).mockResolvedValue(month({ limit: '800', remaining: '320' }))
    render(<CreditRulePreview userId={2} credits="100" enabled />)
    expect(await screen.findByRole('status')).toHaveTextContent('dsh.unified.previewHigherRule {"limit":"800"}')
})

it('says the member becomes uncapped when no rule applies', async () => {
    vi.mocked(getUserCredits).mockResolvedValue(month({ unlimited: true, limit: '9223372036854.775807', remaining: '9223372036374.775807' }))
    render(<CreditRulePreview userId={2} credits="1000" enabled={false} />)
    expect(await screen.findByRole('status')).toHaveTextContent('dsh.unified.previewUnlimited {"used":"480"}')
})

it('asks nothing for an invalid allowance and stays quiet when the preview fails', async () => {
    const { rerender } = render(<CreditRulePreview userId={2} credits="0.01" enabled />)
    await new Promise((resolve) => setTimeout(resolve, 400))
    expect(getUserCredits).not.toHaveBeenCalled()
    vi.mocked(getUserCredits).mockRejectedValue(new Error('offline'))
    rerender(<CreditRulePreview userId={2} credits="10" enabled />)
    await waitFor(() => expect(getUserCredits).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('status')).toBeNull()
})
