import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { getModelPricingRows, matchPriceCatalog } from '@/controllers/API/modelPricing'
import type { ModelPricingRow } from '@/controllers/API/modelPricing'
import { UserSelectableModels } from './UserSelectableModels'
import { updateModelMetadata } from './userModelMetadata'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./dsh/ModelVisionSwitch', () => ({ ModelVisionSwitch: () => <span>vision-control</span> }))
vi.mock('./dsh/BaseModelPicker', () => ({ BaseModelPicker: () => <span>base-picker</span> }))
vi.mock('./dsh/ModelAccessDialog', () => ({ ModelAccessDialog: ({ model }: { model: { name: string } | null }) => model ? <p role="dialog">{model.name}</p> : null }))
vi.mock('@/controllers/API/modelPricing', () => ({
    getModelPricingRows: vi.fn(),
    getModelVisionRows: vi.fn(async () => []),
    getCreditSettings: vi.fn(async () => ({ version: 2, currency: 'CNY', credit_value: '0.01', usd_cny_rate: '7.2', base_model_id: null })),
    saveCreditSettings: vi.fn(),
    saveModelPricing: vi.fn(),
    matchPriceCatalog: vi.fn(async () => ({ matched: false, via_name: false, catalog_version: 'v', entry: null })),
}))

const priced = (model_id: number, changes: Partial<ModelPricingRow> = {}): ModelPricingRow => ({
    model_id,
    pricing: { currency: 'USD', input: '1.25', cache_read: '0.125', cache_write: null, output: '3.75', source: 'CATALOG', revision: 1 },
    effective: { currency: 'CNY', input: '9', cache_read: '0.9', cache_write: '9', output: '27' },
    edited: false,
    missing: false,
    hint: { ratio: '3.00', base: false, free: false },
    can_edit: true, read_only: false, source_tenant_id: 1, base_reason: null,
    ...changes,
})

beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getModelPricingRows).mockResolvedValue([
        priced(42),
        priced(44, { pricing: null, effective: null, missing: true, hint: { ratio: null, base: false, free: false } }),
        priced(45, {
            pricing: { currency: 'CNY', input: '0', cache_read: '0', output: '0', source: 'DEFAULT', revision: 1 },
            effective: { currency: 'CNY', input: '0', cache_read: '0', cache_write: '0', output: '0' },
            hint: { ratio: null, base: false, free: true },
        }),
        priced(46, { hint: { ratio: '1.00', base: true, free: false } }),
    ])
})

const servers = [{ id: 1, name: 'Provider A', models: [
    { id: 42, model_name: 'vendor-model', model_type: 'llm', online: true },
    { id: 43, model_name: 'offline', model_type: 'llm', online: false },
    { id: 44, model_name: 'unpriced', model_type: 'llm', online: true },
    { id: 45, model_name: 'local-free', model_type: 'llm', online: true },
    { id: 46, model_name: 'base-model', model_type: 'llm', online: true },
] }]

it('edits display metadata and opens visibility without a permission summary or default columns', async () => {
    const change = vi.fn()
    render(<UserSelectableModels data={servers} configuredModels={[{ id: '42', displayName: 'Display label', description: 'kept' }]}
        enterpriseEnabled disabled={false} onMetadataChange={change} />)
    expect(screen.getAllByText('Provider A')[0]).toBeVisible()
    expect(screen.queryByText('offline')).toBeNull()
    expect(screen.getAllByRole('columnheader')).toHaveLength(7)
    const input = screen.getByRole('textbox', { name: 'model.displayName · vendor-model' })
    expect(input).toHaveValue('Display label')
    fireEvent.change(input, { target: { value: 'Renamed' } })
    expect(change).toHaveBeenCalledWith(expect.objectContaining({ id: 42 }), { displayName: 'Renamed' })
    fireEvent.click(screen.getAllByRole('button', { name: 'model.configureVisibility' })[0])
    expect(screen.getByRole('dialog')).toHaveTextContent('Display label')
    expect(screen.queryByText('kept')).toBeNull()
})

it('shows the server-computed ratio and price of each model, marking base, free and unpriced models', async () => {
    render(<UserSelectableModels data={servers} configuredModels={[]} enterpriseEnabled disabled={false} onMetadataChange={vi.fn()} />)
    const rowOf = async (name: string) => (await screen.findByText(name)).closest('tr') as HTMLElement
    expect(within(await rowOf('vendor-model')).getByText('3.00x')).toBeVisible()
    expect(within(await rowOf('base-model')).getByText('dsh.pricing.base')).toBeVisible()
    const free = await rowOf('local-free')
    expect(within(free).getByText('dsh.pricing.free')).toBeVisible()
    expect(within(free).getByText('dsh.pricing.defaultTag')).toBeVisible()
    const unpriced = await rowOf('unpriced')
    expect(within(unpriced).getByText('dsh.pricing.missingTag')).toBeVisible()
    expect(screen.getByText('base-picker')).toBeVisible()
})

it('opens the price editor for priced and unpriced models with the provider type for the catalog', async () => {
    render(<UserSelectableModels data={[{ ...servers[0], type: 'openai' }]} configuredModels={[]} enterpriseEnabled disabled={false} onMetadataChange={vi.fn()} />)
    expect(await screen.findByRole('button', { name: 'dsh.pricing.editPrice · unpriced' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'dsh.pricing.editPrice · vendor-model' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('dsh.pricing.priceDialogTitle · vendor-model')
    expect(within(dialog).getByRole('textbox', { name: 'model.pricing.output' })).toHaveValue('3.75')
    await waitFor(() => expect(matchPriceCatalog).toHaveBeenCalledWith('openai', 'vendor-model', expect.any(AbortSignal)))
})

it('keeps the community table free of pricing requests', () => {
    render(<UserSelectableModels data={servers} configuredModels={[]} enterpriseEnabled={false} disabled={false} onMetadataChange={vi.fn()} />)
    // Visibility is a platform column; ratio and price need the desktop module.
    expect(screen.getAllByRole('columnheader')).toHaveLength(5)
    expect(screen.queryByRole('columnheader', { name: /dsh.pricing/ })).toBeNull()
    expect(getModelPricingRows).not.toHaveBeenCalled()
})

it('preserves hidden descriptions and offline rows while adding a desktop-only model label', () => {
    const original = [{ id: '1', displayName: 'Existing', description: 'Keep this', visual: true }]
    const renamed = updateModelMetadata(original, { id: 1, model_name: 'vendor' }, { displayName: 'New' })
    expect(renamed).toEqual([{ ...original[0], displayName: 'New' }])
    const added = updateModelMetadata(renamed, { id: 2, model_name: 'desktop-only' }, { displayName: 'Desktop label' })
    expect(added[0]).toEqual(renamed[0])
    expect(added[1]).toEqual({ id: '2', key: '2', name: 'desktop-only', displayName: 'Desktop label' })
    expect(original[0].displayName).toBe('Existing')
})

it('offers visibility without the desktop module but no credit multiplier', () => {
    render(<UserSelectableModels data={[{ id: 1, name: 'Provider A', models: [
        { id: 42, model_name: 'vendor-model', model_type: 'llm', online: true },
    ] }]} configuredModels={[]} enterpriseEnabled={false} disabled={false} onMetadataChange={vi.fn()} />)
    expect(screen.getByText('model.userSelectableModelsHelpBasic')).toBeVisible()
    expect(screen.getAllByRole('columnheader')).toHaveLength(5)
    expect(screen.getByRole('columnheader', { name: 'model.visibilityScope' })).toBeVisible()
    expect(screen.queryByText('rate-control')).toBeNull()
    expect(screen.getByText('vision-control')).toBeVisible()
    // No display name or vision edit is needed for the model to be configurable.
    fireEvent.click(screen.getByRole('button', { name: 'model.configureVisibility' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('vendor-model')
})
