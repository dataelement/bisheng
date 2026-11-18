import { render, screen, waitFor } from '@/test/test-utils'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { getCreditSettings, saveCreditSettings, type CreditSettings } from '@/controllers/API/modelPricing'
import { CreditSettingsPanel } from './CreditSettingsPanel'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => values ? `${key}(${Object.values(values).join('|')})` : key,
    }),
}))
vi.mock('@/controllers/API/modelPricing', () => ({
    getCreditSettings: vi.fn(),
    saveCreditSettings: vi.fn(),
    getModelPricingRows: vi.fn(async () => []),
}))

const SAVED: CreditSettings = {
    version: 3, currency: 'CNY', credit_value: '0.01', usd_cny_rate: '7.2', base_model_id: 46, effective_base_model_id: 46,
}

beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getCreditSettings).mockResolvedValue(SAVED)
    vi.mocked(saveCreditSettings).mockImplementation(async value => ({ ...value, version: value.version + 1 }))
})

const creditField = () => screen.findByRole('textbox', { name: 'dsh.pricing.creditValue' })

it('keeps the budget by default when the billing currency changes', async () => {
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    expect(await creditField()).toHaveValue('0.01')
    expect(screen.getByRole('button', { name: 'dsh.pricing.save' })).toBeDisabled()
    await user.click(screen.getByRole('radio', { name: 'dsh.pricing.currencyUSD' }))
    // 0.01 yuan at 7.2 yuan per dollar
    expect(await creditField()).toHaveValue('0.001389')
    expect(screen.getByRole('radio', { name: /dsh.pricing.keepBudget/ })).toBeChecked()
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.save' }))
    await waitFor(() => expect(saveCreditSettings).toHaveBeenCalledWith(expect.objectContaining({
        version: 3, currency: 'USD', credit_value: '0.001389', usd_cny_rate: '7.2', base_model_id: 46,
    })))
    expect(await screen.findByRole('status')).toHaveTextContent('dsh.pricing.saved')
})

it('can keep the number instead and follows a new rate while keeping the budget', async () => {
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    await creditField()
    await user.click(screen.getByRole('radio', { name: 'dsh.pricing.currencyUSD' }))
    const rate = screen.getByRole('textbox', { name: 'dsh.pricing.rate' })
    await user.clear(rate)
    await user.type(rate, '8')
    expect(await creditField()).toHaveValue('0.00125')
    await user.click(screen.getByRole('radio', { name: /dsh.pricing.keepNumber/ }))
    expect(await creditField()).toHaveValue('0.01')
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.save' }))
    await waitFor(() => expect(saveCreditSettings).toHaveBeenCalledWith(expect.objectContaining({
        currency: 'USD', credit_value: '0.01', usd_cny_rate: '8',
    })))
})

it('blocks values outside the server range', async () => {
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    const credit = await creditField()
    await user.clear(credit)
    await user.type(credit, '0.00001')
    expect(screen.getByRole('alert')).toHaveTextContent('dsh.pricing.creditValueInvalid')
    expect(screen.getByRole('button', { name: 'dsh.pricing.save' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.cancel' }))
    expect(await creditField()).toHaveValue('0.01')
    expect(screen.queryByRole('alert')).toBeNull()
})

it('explains a concurrent edit and keeps the draft', async () => {
    vi.mocked(saveCreditSettings).mockRejectedValue({ status_code: 26130 })
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    const credit = await creditField()
    await user.clear(credit)
    await user.type(credit, '0.02')
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.pricing.conflict')
    expect(credit).toHaveValue('0.02')
})

it('offers a retry when the settings cannot be read', async () => {
    vi.mocked(getCreditSettings).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(SAVED)
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.pricing.unavailable')
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.refresh' }))
    expect(await creditField()).toHaveValue('0.01')
})
