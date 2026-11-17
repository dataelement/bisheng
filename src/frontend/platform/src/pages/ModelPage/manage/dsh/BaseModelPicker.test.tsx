import { render, screen, selectOption, waitFor } from '@/test/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import {
    getCreditSettings, saveCreditSettings, type CreditSettings, type ModelPricingRow,
} from '@/controllers/API/modelPricing'
import { BaseModelPicker } from './BaseModelPicker'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/API/modelPricing', () => ({
    getCreditSettings: vi.fn(),
    saveCreditSettings: vi.fn(),
    getModelPricingRows: vi.fn(async () => []),
}))

const SAVED: CreditSettings = {
    version: 3, currency: 'CNY', credit_value: '0.01', usd_cny_rate: '7.2', base_model_id: null, effective_base_model_id: 46,
}
const row = (model_id: number, hint: ModelPricingRow['hint'], missing = false): ModelPricingRow => ({
    model_id, pricing: null, effective: null, edited: false, missing, hint,
})
const models = [{ id: 46, label: 'Chat default' }, { id: 47, label: 'Local model' }]

beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getCreditSettings).mockResolvedValue(SAVED)
    vi.mocked(saveCreditSettings).mockImplementation(async value => ({ ...value, version: 4, effective_base_model_id: value.base_model_id }))
})

it('saves the chosen base model with the loaded version', async () => {
    const rows = new Map([[46, row(46, { ratio: '1.00', base: true, free: false })], [47, row(47, { ratio: '0.50', base: false, free: false })]])
    render(<BaseModelPicker models={models} rows={rows} />)
    await waitFor(() => expect(getCreditSettings).toHaveBeenCalled())
    expect(screen.queryByText('dsh.pricing.baseUnavailable')).toBeNull()
    await selectOption('dsh.pricing.baseModel', 'Local model')
    await waitFor(() => expect(saveCreditSettings).toHaveBeenCalledWith(expect.objectContaining({ version: 3, base_model_id: 47 })))
    expect(await screen.findByLabelText('dsh.pricing.saved')).toBeInTheDocument()
})

it('says so when the base model cannot anchor the ratios', async () => {
    const rows = new Map([[46, row(46, { ratio: null, base: true, free: true })]])
    render(<BaseModelPicker models={models} rows={rows} />)
    expect(await screen.findByText('dsh.pricing.baseUnavailable')).toBeVisible()
})

it('shows a conflict without changing the selection', async () => {
    vi.mocked(saveCreditSettings).mockRejectedValue({ status_code: 26130 })
    render(<BaseModelPicker models={models} rows={new Map()} />)
    await waitFor(() => expect(getCreditSettings).toHaveBeenCalled())
    await selectOption('dsh.pricing.baseModel', 'Local model')
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.pricing.conflict')
})
