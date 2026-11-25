import { render, screen, waitFor, within } from '@/test/test-utils'
import userEvent from '@testing-library/user-event'
import { toast } from '@bisheng/ui'
import { beforeEach, expect, it, vi } from 'vitest'
import { matchPriceCatalog, saveModelPricing, type ModelPricingRow } from '@/controllers/API/modelPricing'
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import { ModelPriceDialog, type PricedModel } from './ModelPriceDialog'

// The confirmation answers "确认保存" unless a test declines it.
const confirmation = vi.hoisted(() => ({ accept: true }))
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({
    bsConfirm: vi.fn((params: { onOk?: (close: () => void) => void; onClose?: () => void }) =>
        confirmation.accept ? params.onOk?.(() => params.onClose?.()) : params.onClose?.()),
}))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => values ? `${key}(${Object.values(values).join('|')})` : key,
    }),
}))
vi.mock('@bisheng/ui', async () => {
    const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui')
    return { ...actual, toast: { ...actual.toast, show: vi.fn() } }
})
vi.mock('@/controllers/API/modelPricing', () => ({
    matchPriceCatalog: vi.fn(),
    saveModelPricing: vi.fn(),
    getModelPricingRows: vi.fn(async () => []),
    getCreditSettings: vi.fn(async () => ({ version: 1, currency: 'CNY', credit_value: '0.01', usd_cny_rate: '7.2', base_model_id: null })),
}))

const SETTINGS = { version: 1, currency: 'CNY' as const, credit_value: '0.01', usd_cny_rate: '7.2', base_model_id: null }
const row = (changes: Partial<ModelPricingRow> = {}): ModelPricingRow => ({
    model_id: 42,
    can_edit: true, read_only: false, source_tenant_id: 1, base_reason: null,
    pricing: { currency: 'USD', input: '1.25', cache_read: '0.125', cache_write: null, output: '3.75', source: 'MANUAL', revision: 3 },
    effective: { currency: 'CNY', input: '9', cache_read: '0.9', cache_write: '9', output: '27' },
    edited: true,
    missing: false,
    hint: { ratio: '1.00', base: true, free: false },
    ...changes,
})
const model = (changes: Partial<ModelPricingRow> = {}): PricedModel => ({
    id: 42, name: 'Display', modelName: 'gpt-4.1', providerType: 'openai', row: row(changes),
})
const field = (name: string) => screen.getByRole('textbox', { name })

beforeEach(() => {
    vi.clearAllMocks()
    confirmation.accept = true
    vi.mocked(matchPriceCatalog).mockResolvedValue({ matched: false, via_name: false, catalog_version: 'v', entry: null })
    vi.mocked(saveModelPricing).mockImplementation(async (_id, pricing) => ({ ...pricing, revision: 4 }))
})

it('edits the stored price in place and sends the revision it was read at', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<ModelPriceDialog model={model()} settings={SETTINGS} onClose={close} />)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('dsh.pricing.priceDialogTitle · Display')
    expect(field('model.pricing.input')).toHaveValue('1.25')
    expect(field('model.pricing.output')).toHaveValue('3.75')
    // 1.25 / 3.75 USD at 7.2 is 9 / 27 CNY: (3000 x 9 + 1000 x 27) / 1e6 / 0.01 = 5.4 credits.
    expect(within(dialog).getByText('dsh.pricing.typical(5.4)')).toBeVisible()
    const save = within(dialog).getByRole('button', { name: 'dsh.pricing.save' })
    expect(save).toBeDisabled()
    await user.clear(field('model.pricing.output'))
    await user.type(field('model.pricing.output'), '5')
    expect(within(dialog).getByText('dsh.pricing.typical(6.3)')).toBeVisible()
    await user.click(save)
    await waitFor(() => expect(close).toHaveBeenCalledOnce())
    expect(saveModelPricing).toHaveBeenCalledWith(42, {
        currency: 'USD', input: '1.25', cache_read: '0.125', cache_write: null, output: '5', revision: 3,
    })
    expect(toast.show).toHaveBeenCalledWith({ type: 'success', message: 'dsh.pricing.priceSaved' })
})

it('starts a model without a price from the catalog suggestion', async () => {
    vi.mocked(matchPriceCatalog).mockResolvedValue({
        matched: true, via_name: false, catalog_version: 'v',
        entry: { key: 'openai/gpt-4.1', vendor: 'OpenAI', label: 'gpt-4.1', provider_types: ['openai'], aliases: ['gpt-4.1'],
            currency: 'USD', input: '2', cache_read: '0.5', cache_write: null, output: '8', source_url: 'https://x', verified_at: '2026-11-10' },
    })
    const user = userEvent.setup()
    render(<ModelPriceDialog model={model({ pricing: null, effective: null, missing: true })} settings={SETTINGS} onClose={vi.fn()} />)
    await waitFor(() => expect(field('model.pricing.output')).toHaveValue('8'))
    expect(matchPriceCatalog).toHaveBeenCalledWith('openai', 'gpt-4.1', expect.any(AbortSignal))
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.save' }))
    await waitFor(() => expect(saveModelPricing).toHaveBeenCalledWith(42, expect.objectContaining({ input: '2', output: '8' })))
    // No stored price yet, so no revision is sent and the server accepts it as the first one.
    expect(vi.mocked(saveModelPricing).mock.calls[0][1].revision).toBeUndefined()
})

it('keeps the dialog open with the server reason when someone else saved first', async () => {
    vi.mocked(saveModelPricing).mockRejectedValue(Object.assign(new Error('The model price was changed by someone else.'), { code: 10813 }))
    const user = userEvent.setup()
    const close = vi.fn()
    render(<ModelPriceDialog model={model()} settings={SETTINGS} onClose={close} />)
    await user.clear(field('model.pricing.input'))
    await user.type(field('model.pricing.input'), '2')
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The model price was changed by someone else.')
    expect(close).not.toHaveBeenCalled()
})

it('blocks saving an invalid price', async () => {
    const user = userEvent.setup()
    render(<ModelPriceDialog model={model()} settings={SETTINGS} onClose={vi.fn()} />)
    await user.clear(field('model.pricing.input'))
    await user.type(field('model.pricing.input'), '-1')
    expect(screen.getByRole('button', { name: 'dsh.pricing.save' })).toBeDisabled()
    expect(saveModelPricing).not.toHaveBeenCalled()
})

it('asks before saving a changed price, listing the price before and after', async () => {
    const user = userEvent.setup()
    render(<ModelPriceDialog model={model()} settings={SETTINGS} onClose={vi.fn()} />)
    await user.clear(field('model.pricing.output'))
    await user.type(field('model.pricing.output'), '5')
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.save' }))
    await waitFor(() => expect(saveModelPricing).toHaveBeenCalledOnce())
    expect(bsConfirm).toHaveBeenCalledOnce()
    const params = vi.mocked(bsConfirm).mock.calls[0][0]
    // Reversible, so the primary tone rather than the red delete one.
    expect(params.variant).toBe('default')
    render(<>{params.desc}</>)
    expect(screen.getByText('$3.75')).toBeVisible()
    expect(screen.getByText('$5')).toBeVisible()
})

it('keeps the edited price unsaved when the confirmation is declined', async () => {
    confirmation.accept = false
    const user = userEvent.setup()
    const close = vi.fn()
    render(<ModelPriceDialog model={model()} settings={SETTINGS} onClose={close} />)
    await user.clear(field('model.pricing.output'))
    await user.type(field('model.pricing.output'), '5')
    await user.click(screen.getByRole('button', { name: 'dsh.pricing.save' }))
    await waitFor(() => expect(bsConfirm).toHaveBeenCalledOnce())
    expect(saveModelPricing).not.toHaveBeenCalled()
    expect(close).not.toHaveBeenCalled()
    expect(field('model.pricing.output')).toHaveValue('5')
})
