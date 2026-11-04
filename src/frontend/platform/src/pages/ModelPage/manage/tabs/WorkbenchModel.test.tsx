import { fireEvent, render, screen, waitFor } from '@/test/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import WorkbenchModel from './WorkbenchModel'
const mocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), message: vi.fn(), t: (key: string) => key }))
vi.mock('@/components/bs-icons/loading', () => ({ LoadingIcon: () => null, LoadIcon: () => null }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }))
vi.mock('@/hooks/useDshBrowserConfig', () => ({ useDshBrowserConfig: () => ({ config: { enabled: true } }) }))
vi.mock('@/components/bs-ui/toast/use-toast', () => ({ useToast: () => ({ message: mocks.message }) }))
vi.mock('@bisheng/ui', async (importOriginal) => ({
    ...await importOriginal<typeof import('@bisheng/ui')>(),
    toast: { show: mocks.message },
}))
vi.mock('@/controllers/API/finetune', () => ({ getLinsightModelEnvelope: mocks.get, updateLinsightModelConfig: mocks.save }))
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))
vi.mock('..', () => ({ useModel: () => ({ llmOptions: [{ value: 'provider', label: 'Provider', children: [{ value: '42', label: 'Original' }, { value: '99', label: 'Hidden' }, { value: '7', label: 'New model' }] }], embeddings: [], asrModel: [], ttsModel: [] }) }))
vi.mock('@/components/bs-ui/select/cascader', () => ({ default: () => null }))
vi.mock('../dsh/ModelVisionSwitch', () => ({ ModelVisionSwitch: () => null }))
vi.mock('../dsh/ModelMultiplierInput', () => ({ ModelMultiplierInput: () => null }))
vi.mock('../dsh/ModelAccessDialog', () => ({ ModelAccessDialog: () => null }))
const config = {
    models: [{ id: '42', displayName: 'Original', description: 'Retained' }, { id: '99', displayName: 'Hidden' }],
    embedding_model: { id: '3' }, chat_default_model_id: '99', linsight_default_model_id: '42',
    abstract_prompt: 'Keep prompt', knowledge_space_llm: { id: '4' },
}
const data = [{ id: 1, name: 'Provider', models: [{ id: 42, model_name: 'vendor', model_type: 'llm', online: true }] }]
beforeEach(() => {
    vi.clearAllMocks()
    mocks.get.mockResolvedValue({ data: config })
    mocks.save.mockResolvedValue(true)
})
it('saves edited names with hidden rows, descriptions and defaults', async () => {
    render(<WorkbenchModel data={data} onBack={vi.fn()} />)
    const input = await screen.findByRole('textbox', { name: 'model.displayName · vendor' })
    await waitFor(() => expect(input).toHaveValue('Original'))
    fireEvent.change(input, { target: { value: ' Renamed ' } })
    fireEvent.click(screen.getByRole('button', { name: 'model.save' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({
        models: [{ ...config.models[0], displayName: 'Renamed' }, config.models[1]],
        chat_default_model_id: '99', linsight_default_model_id: '42',
        abstract_prompt: 'Keep prompt', knowledge_space_llm: { id: '4' },
    })))
})
it('keeps the draft available after a failed save', async () => {
    mocks.save.mockRejectedValue(new Error('Failed'))
    render(<WorkbenchModel data={data} onBack={vi.fn()} />)
    const input = await screen.findByRole('textbox', { name: 'model.displayName · vendor' })
    await waitFor(() => expect(input).toHaveValue('Original'))
    fireEvent.change(input, { target: { value: 'Draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'model.save' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.getByRole('button', { name: 'model.save' })).toBeEnabled())
    expect(input).toHaveValue('Draft')
    expect(mocks.get).toHaveBeenCalledOnce()
    expect(mocks.message).not.toHaveBeenCalledWith(expect.objectContaining({ variant: 'success' }))
})

it('exposes both mode defaults in other model settings', async () => {
    render(<WorkbenchModel data={data} onBack={vi.fn()} />)
    await screen.findByRole('button', { name: 'model.save' })
    expect(screen.getAllByLabelText('model.linsightDefaultModel').length).toBeGreaterThan(0)
    expect(screen.getAllByLabelText('model.dailyDefaultModel').length).toBeGreaterThan(0)
})

it('adds a newly chosen default to the saved selectable catalog', async () => {
    render(<WorkbenchModel data={data} onBack={vi.fn()} />)
    await screen.findByRole('button', { name: 'model.save' })
    fireEvent.click(screen.getByText('model.otherModelSettings'))
    fireEvent.click(screen.getByRole('combobox', { name: 'model.dailyDefaultModel' }))
    fireEvent.click((await screen.findAllByText('Provider')).at(-1)!)
    fireEvent.click(await screen.findByText('New model'))
    fireEvent.click(screen.getByRole('button', { name: 'model.save' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({
        chat_default_model_id: '7',
        models: expect.arrayContaining([expect.objectContaining({ id: '7', displayName: 'New model' })]),
    })))
})
