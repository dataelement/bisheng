import { render, screen, waitFor } from '@/test/test-utils'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import { getCreditSettings, saveCreditSettings, type CreditSettings } from '@/controllers/API/modelPricing'
import { act } from 'react'
import { CreditSettingsPanel } from './CreditSettingsPanel'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => values ? `${key}(${Object.values(values).join('|')})` : key,
    }),
}))
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }))
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

it('picks the billing currency right after the credit value instead of in its own row', async () => {
    render(<CreditSettingsPanel />)
    const credit = await creditField()
    const currency = screen.getByRole('radio', { name: 'dsh.pricing.currencyCNY' })
    expect(currency).toBeChecked()
    // Inside the credit value field itself, and no separate "billing currency" heading above it.
    expect(credit.closest('div.space-y-1')).toContainElement(currency)
    expect(screen.queryByText('dsh.pricing.currency')).toBeNull()
})

const confirmSwitch = () => {
    const params = vi.mocked(bsConfirm).mock.calls.at(-1)![0]
    act(() => { void params.onOk?.(() => undefined) })
    return params
}

it('asks before switching the billing currency and keeps the number', async () => {
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    expect(await creditField()).toHaveValue('0.01')
    expect(screen.getByRole('button', { name: 'dsh.pricing.save' })).toBeDisabled()
    await user.click(screen.getByRole('radio', { name: 'dsh.pricing.currencyUSD' }))
    // Nothing changes until the administrator confirms.
    expect(bsConfirm).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('radio', { name: 'dsh.pricing.currencyCNY' })).toBeChecked()
    const params = confirmSwitch()
    expect(params.variant).toBe('default')
    expect(params.title).toBe('dsh.pricing.switchCurrencyTitle(dsh.pricing.currencyUSD)')
    // value | from | to | rate | times: one credit becomes worth 7.2 times as much
    expect(params.desc).toBe('dsh.pricing.switchCurrencyDesc(0.01|dsh.pricing.currencyCNY|dsh.pricing.currencyUSD|7.2|7.2)')
    expect(params.okTxt).toBe('dsh.pricing.switchCurrencyOk')
    expect(params.canelTxt).toBe('dsh.pricing.switchCurrencyCancel')
    expect(screen.getByRole('radio', { name: 'dsh.pricing.currencyUSD' })).toBeChecked()
    expect(await creditField()).toHaveValue('0.01')
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.save' }))
    await waitFor(() => expect(saveCreditSettings).toHaveBeenCalledWith(expect.objectContaining({
        version: 3, currency: 'USD', credit_value: '0.01', usd_cny_rate: '7.2', base_model_id: 46,
    })))
    expect(await screen.findByRole('status')).toHaveTextContent('dsh.pricing.saved')
})

it('stays on the current currency when the switch is not confirmed', async () => {
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    await creditField()
    await user.click(screen.getByRole('radio', { name: 'dsh.pricing.currencyUSD' }))
    expect(bsConfirm).toHaveBeenCalledTimes(1)
    // The confirmation closed through "Not now": onOk never runs.
    expect(screen.getByRole('radio', { name: 'dsh.pricing.currencyCNY' })).toBeChecked()
    expect(screen.getByRole('button', { name: 'dsh.pricing.save' })).toBeDisabled()
    expect(saveCreditSettings).not.toHaveBeenCalled()
})

it('undoes an unsaved switch without asking again', async () => {
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    await creditField()
    await user.click(screen.getByRole('radio', { name: 'dsh.pricing.currencyUSD' }))
    confirmSwitch()
    expect(screen.getByRole('radio', { name: 'dsh.pricing.currencyUSD' })).toBeChecked()
    await user.click(screen.getByRole('radio', { name: 'dsh.pricing.currencyCNY' }))
    // Back on the saved currency: no second confirmation and nothing left to save.
    expect(bsConfirm).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('radio', { name: 'dsh.pricing.currencyCNY' })).toBeChecked()
    expect(screen.getByRole('button', { name: 'dsh.pricing.save' })).toBeDisabled()
})

it('states the reverse factor when switching back to CNY', async () => {
    vi.mocked(getCreditSettings).mockResolvedValue({ ...SAVED, currency: 'USD' })
    const user = userEvent.setup()
    render(<CreditSettingsPanel />)
    await creditField()
    await user.click(screen.getByRole('radio', { name: 'dsh.pricing.currencyCNY' }))
    // 1 / 7.2 rounded to 4 decimals
    expect(confirmSwitch().desc).toBe('dsh.pricing.switchCurrencyDesc(0.01|dsh.pricing.currencyUSD|dsh.pricing.currencyCNY|7.2|0.1389)')
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
