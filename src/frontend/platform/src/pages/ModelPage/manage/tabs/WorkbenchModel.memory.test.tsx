import { fireEvent, render, screen, waitFor } from '@/test/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '../../../../../public/locales/en-US/model.json'
import ja from '../../../../../public/locales/ja/model.json'
import zh from '../../../../../public/locales/zh-Hans/model.json'
import WorkbenchModel from './WorkbenchModel'

// F132 AC-106: the memory consolidation model lives in the workbench section of the system model settings.
const mocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), message: vi.fn(), t: (key: string) => key }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }))
vi.mock('@/hooks/useDshBrowserConfig', () => ({ useDshBrowserConfig: () => ({ config: { enabled: true } }) }))
vi.mock('@bisheng/ui', async (importOriginal) => ({
    ...await importOriginal<typeof import('@bisheng/ui')>(),
    toast: { show: mocks.message },
}))
vi.mock('@/controllers/API/finetune', () => ({ getLinsightModelEnvelope: mocks.get, updateLinsightModelConfig: mocks.save }))
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))
vi.mock('..', () => ({ useModel: () => ({ llmOptions: [{ value: 'provider', label: 'Provider', children: [{ value: '42', label: 'Original' }, { value: '7', label: 'Memory model' }] }], embeddings: [], asrModel: [], ttsModel: [] }) }))
vi.mock('../dsh/ModelVisionSwitch', () => ({ ModelVisionSwitch: () => null }))
vi.mock('../dsh/ModelMultiplierInput', () => ({ ModelMultiplierInput: () => null }))
vi.mock('../dsh/ModelAccessDialog', () => ({ ModelAccessDialog: () => null }))

const config = {
    models: [{ id: '42', displayName: 'Original' }],
    embedding_model: { id: '3' }, chat_default_model_id: '42', linsight_default_model_id: '42',
}
const data = [{ id: 1, name: 'Provider', models: [{ id: 42, model_name: 'vendor', model_type: 'llm', online: true }] }]

beforeEach(() => {
    vi.clearAllMocks()
    mocks.save.mockResolvedValue(true)
})

describe('memory consolidation model (AC-106)', () => {
    it('saves the chosen model as memory_llm', async () => {
        mocks.get.mockResolvedValue({ data: config })
        render(<WorkbenchModel data={data} onBack={vi.fn()} />)
        await screen.findByRole('button', { name: 'model.save' })
        fireEvent.click(screen.getByText('model.otherModelSettings'))
        fireEvent.click(screen.getByRole('combobox', { name: 'model.memoryLlm' }))
        fireEvent.click((await screen.findAllByText('Provider')).at(-1)!)
        fireEvent.click(await screen.findByText('Memory model'))
        fireEvent.click(screen.getByRole('button', { name: 'model.save' }))
        await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ memory_llm: { id: '7' } })))
    })

    it('keeps a saved value and sends null when nothing is selected', async () => {
        mocks.get.mockResolvedValue({ data: { ...config, memory_llm: { id: '7' } } })
        const { unmount } = render(<WorkbenchModel data={data} onBack={vi.fn()} />)
        await screen.findByRole('button', { name: 'model.save' })
        fireEvent.click(screen.getByRole('button', { name: 'model.save' }))
        await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ memory_llm: { id: '7' } })))
        unmount()

        mocks.save.mockClear()
        mocks.get.mockResolvedValue({ data: config })
        render(<WorkbenchModel data={data} onBack={vi.fn()} />)
        await screen.findByRole('button', { name: 'model.save' })
        fireEvent.click(screen.getByRole('button', { name: 'model.save' }))
        await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ memory_llm: null })))
    })

    it('ships the label and hint in three languages', () => {
        // "Memory organization model" in zh-Hans, built from code points to keep source free of CJK literals.
        expect(zh.model.memoryLlm).toBe(String.fromCodePoint(0x8bb0, 0x5fc6, 0x6574, 0x7406, 0x6a21, 0x578b))
        for (const locale of [zh, en, ja]) {
            expect(locale.model.memoryLlm.length).toBeGreaterThan(0)
            expect(locale.model.memoryLlmTooltip.length).toBeGreaterThan(0)
        }
    })
})
