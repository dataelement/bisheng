import { fireEvent, render, screen, waitFor } from '@/test/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { SystemModelDiagnostics } from './SystemModelDiagnostics'
import { getSystemModelSettings, restoreModelInheritance } from '@/controllers/API/systemModelSettings'

const confirm = vi.hoisted(() => vi.fn())
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: confirm }))
vi.mock('@/controllers/API/systemModelSettings', () => ({
    getSystemModelSettings: vi.fn(), restoreModelInheritance: vi.fn(),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

beforeEach(() => { vi.clearAllMocks() })
it('preserves an unavailable inherited model and explains why it cannot run', async () => {
    vi.mocked(getSystemModelSettings).mockResolvedValue({ tenant_id: 69, sections: [{
        key: 'knowledge_llm', inherited_from_root: true, fallback_blocked: false,
        references: [{ slot_key: 'embedding_model_id', model_id: 934, model_name: 'Root embedding', status: 'not_shared' }],
    }] })
    render(<SystemModelDiagnostics configKey="knowledge_llm" scopeKey="user:1:69" onRestored={vi.fn()} />)
    expect(await screen.findByText('model.settingsInherited')).toBeVisible()
    expect(screen.getByText(/Root embedding/)).toHaveTextContent('model.referenceStatus.not_shared')
    expect(screen.queryByRole('button', { name: 'model.restoreInheritance' })).toBeNull()
})

it('restores only the current column after an explicit confirmation', async () => {
    vi.mocked(getSystemModelSettings).mockResolvedValue({ tenant_id: 69, sections: [{
        key: 'assistant_llm', inherited_from_root: false, fallback_blocked: false, references: [],
    }] })
    vi.mocked(restoreModelInheritance).mockResolvedValue(undefined)
    const restored = vi.fn()
    render(<SystemModelDiagnostics configKey="assistant_llm" scopeKey="user:1:69" onRestored={restored} />)
    fireEvent.click(await screen.findByRole('button', { name: 'model.restoreInheritance' }))
    expect(restoreModelInheritance).not.toHaveBeenCalled()
    const next = vi.fn()
    await confirm.mock.calls[0][0].onOk(next)
    expect(restoreModelInheritance).toHaveBeenCalledWith('assistant_llm')
    expect(restored).toHaveBeenCalledOnce()
    expect(next).toHaveBeenCalledOnce()
})

it('leaves the confirmation open when restoring inheritance fails', async () => {
    vi.mocked(getSystemModelSettings).mockResolvedValue({ tenant_id: 69, sections: [{
        key: 'workflow_llm', inherited_from_root: false, fallback_blocked: false, references: [],
    }] })
    vi.mocked(restoreModelInheritance).mockRejectedValue(new Error('restore failed'))
    const restored = vi.fn()
    render(<SystemModelDiagnostics configKey="workflow_llm" scopeKey="user:1:69" onRestored={restored} />)
    fireEvent.click(await screen.findByRole('button', { name: 'model.restoreInheritance' }))
    const next = vi.fn()
    await expect(confirm.mock.calls[0][0].onOk(next)).rejects.toThrow('restore failed')
    expect(restoreModelInheritance).toHaveBeenCalledWith('workflow_llm')
    expect(next).not.toHaveBeenCalled()
    expect(restored).not.toHaveBeenCalled()
})

it('does not accept a late response from a retired tenant', async () => {
    let resolveOld: (value: Awaited<ReturnType<typeof getSystemModelSettings>>) => void = () => undefined
    vi.mocked(getSystemModelSettings).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
        .mockResolvedValueOnce({ tenant_id: 70, sections: [{ key: 'knowledge_llm', inherited_from_root: false, fallback_blocked: false, references: [] }] })
    const page = render(<SystemModelDiagnostics key="69" configKey="knowledge_llm" scopeKey="69" onRestored={vi.fn()} />)
    await waitFor(() => expect(getSystemModelSettings).toHaveBeenCalledOnce())
    page.rerender(<SystemModelDiagnostics key="70" configKey="knowledge_llm" scopeKey="70" onRestored={vi.fn()} />)
    expect(await screen.findByText('model.settingsLocal')).toBeVisible()
    resolveOld({ tenant_id: 69, sections: [{ key: 'knowledge_llm', inherited_from_root: true, fallback_blocked: false, references: [] }] })
    await waitFor(() => expect(screen.queryByText('model.settingsInherited')).toBeNull())
})
