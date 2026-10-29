import { fireEvent, render, screen, waitFor } from '@/test/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import WorkbenchModel from './WorkbenchModel'
const mocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), message: vi.fn(), t: (key: string) => key }))
vi.mock('@/components/bs-icons/loading', () => ({ LoadingIcon: () => null, LoadIcon: () => null }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }))
vi.mock('@/hooks/useDshBrowserConfig', () => ({ useDshBrowserConfig: () => ({ config: { enabled: true } }) }))
vi.mock('@/components/bs-ui/toast/use-toast', () => ({ useToast: () => ({ message: mocks.message }) }))
vi.mock('@/controllers/API/finetune', () => ({ getLinsightModelEnvelope: mocks.get, updateLinsightModelConfig: mocks.save }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise.catch(() => false) }))
vi.mock('..', () => ({ useModel: () => ({ llmOptions: [], embeddings: [], asrModel: [], ttsModel: [] }) }))
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
