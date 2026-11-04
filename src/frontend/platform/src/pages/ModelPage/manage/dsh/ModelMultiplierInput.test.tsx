import { fireEvent, render, screen, waitFor } from '@/test/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { getModelVisibility, saveModelVisibility } from '@/controllers/API/dshUnified'
import { ModelMultiplierInput } from './ModelMultiplierInput'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/API/dshUnified', () => ({ getModelVisibility: vi.fn(), saveModelVisibility: vi.fn() }))
vi.mock('@/utils/dshRequestError', () => ({ getDshRequestErrorKey: () => 'dsh.conflict' }))
const initial = { version: 3, everyone: true, subjects: [], credit_multiplier: '1' }
beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getModelVisibility).mockResolvedValue(initial)
    vi.mocked(saveModelVisibility).mockImplementation(async (_, value) => ({ ...value, version: value.version + 1 }))
})
async function setup() {
    const pending = vi.fn()
    render(<ModelMultiplierInput modelId={7} modelName="Model" onSavingChange={pending} />)
    const input = screen.getByRole('textbox')
    await waitFor(() => expect(input).toBeEnabled())
    return { input, pending }
}
it('saves on blur using the current visibility and version, preserving concurrent permission edits', async () => {
    const { input, pending } = await setup()
    const latest = { version: 6, everyone: false, subjects: [{ kind: 'ROLE' as const, id: 10 }], credit_multiplier: '1' }
    vi.mocked(getModelVisibility).mockResolvedValue(latest)
    fireEvent.change(input, { target: { value: '1.25' } })
    fireEvent.blur(input)
    await waitFor(() => expect(saveModelVisibility).toHaveBeenCalledWith(7, { ...latest, credit_multiplier: '1.25' }))
    await waitFor(() => expect(input).toBeEnabled())
    expect(input).toHaveValue('1.25')
    expect(pending.mock.calls).toEqual([[7, true], [7, false]])
    expect(screen.getByLabelText('dsh.unified.saved')).toBeVisible()
})
it('deduplicates Enter and blur while a rate write is pending', async () => {
    const { input } = await setup()
    let finish!: (value: typeof initial) => void
    vi.mocked(saveModelVisibility).mockReturnValue(new Promise(resolve => { finish = resolve }))
    fireEvent.change(input, { target: { value: '1.1' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.blur(input)
    await waitFor(() => expect(saveModelVisibility).toHaveBeenCalledTimes(1))
    expect(input).toBeDisabled()
    finish({ ...initial, version: 4, credit_multiplier: '1.1' })
    await waitFor(() => expect(input).toBeEnabled())
    fireEvent.blur(input)
    expect(saveModelVisibility).toHaveBeenCalledTimes(1)
})
it('keeps a failed draft for retry and refreshes the policy before retrying', async () => {
    const { input } = await setup()
    vi.mocked(saveModelVisibility).mockRejectedValueOnce(new Error('conflict'))
    fireEvent.change(input, { target: { value: '1.25' } })
    fireEvent.blur(input)
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.conflict')
    expect(input).toHaveValue('1.25')
    vi.mocked(getModelVisibility).mockResolvedValue({ ...initial, version: 8 })
    fireEvent.click(screen.getByRole('button', { name: 'dsh.refresh · Model' }))
    await waitFor(() => expect(saveModelVisibility).toHaveBeenLastCalledWith(7, { ...initial, version: 8, credit_multiplier: '1.25' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
})
it('validates the rate before issuing a mutation', async () => {
    const { input } = await setup()
    for (const value of ['0', '-1', '1.001', '1000.01', '']) {
        fireEvent.change(input, { target: { value } })
        fireEvent.blur(input)
        expect(screen.getByRole('alert')).toHaveTextContent('dsh.unified.multiplierInvalid')
        expect(input).toHaveAttribute('aria-invalid', 'true')
    }
    expect(saveModelVisibility).not.toHaveBeenCalled()
})
it('loads the real rate before allowing editing and recovers a failed read', async () => {
    vi.mocked(getModelVisibility).mockRejectedValueOnce(new Error('offline'))
    render(<ModelMultiplierInput modelId={7} modelName="Model" onSavingChange={vi.fn()} />)
    await screen.findByRole('alert')
    expect(screen.getByRole('textbox')).toBeDisabled()
    expect(saveModelVisibility).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'dsh.refresh · Model' }))
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveValue('1'))
    expect(screen.getByRole('textbox')).toBeEnabled()
})
