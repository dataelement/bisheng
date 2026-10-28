import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ModelProviderRow, type ModelProvider } from './ModelProviderRow'

const provider: ModelProvider = {
    id: 1, name: 'Provider', models: [
        { id: 10, model_name: 'Chat', model_type: 'llm', status: 0, online: false },
        { id: 11, model_name: 'Embed', model_type: 'embedding', status: 1, online: true, remark: 'Connection failed' },
    ],
}
afterEach(cleanup)

function setup(overrides: Partial<React.ComponentProps<typeof ModelProviderRow>> = {}) {
    const props = { data: provider, canManage: true, probing: false, onModel: vi.fn(),
        onToggle: vi.fn().mockResolvedValue(true), onVerify: vi.fn().mockResolvedValue(undefined), ...overrides }
    render(<ModelProviderRow {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Provider' }))
    return props
}

describe('model provider list interactions', () => {
    it('expands with a keyboard-focusable button and opens provider configuration', () => {
        const props = setup()
        expect(screen.getByRole('button', { name: 'Provider' })).toHaveAttribute('aria-expanded', 'true')
        expect(screen.getByText('Chat')).toBeVisible()
        fireEvent.click(screen.getByRole('button', { name: 'model.modelConfiguration' }))
        expect(props.onModel).toHaveBeenCalledWith(1)
    })

    it('toggles from row whitespace without toggling when configuring the provider', () => {
        const props = setup()
        const toggle = screen.getByRole('button', { name: 'Provider' })
        const row = toggle.parentElement!.parentElement!
        fireEvent.click(row)
        expect(toggle).toHaveAttribute('aria-expanded', 'false')
        fireEvent.click(row)
        expect(toggle).toHaveAttribute('aria-expanded', 'true')
        fireEvent.click(screen.getByRole('button', { name: 'model.modelConfiguration' }))
        expect(props.onModel).toHaveBeenCalledExactlyOnceWith(1)
        expect(toggle).toHaveAttribute('aria-expanded', 'true')
    })

    it('locks a pending toggle and restores its previous state when the server rejects it', async () => {
        let finish!: (success: boolean) => void
        const onToggle = vi.fn(() => new Promise<boolean>(resolve => { finish = resolve }))
        setup({ onToggle })
        const control = screen.getByRole('switch', { name: 'Chat' })
        fireEvent.click(control)
        expect(control).toBeDisabled()
        expect(control).toHaveAttribute('aria-checked', 'true')
        fireEvent.click(control)
        expect(onToggle).toHaveBeenCalledExactlyOnceWith(10, true)
        await act(async () => { finish(false) })
        expect(control).not.toBeDisabled()
        expect(control).toHaveAttribute('aria-checked', 'false')
    })

    it('keeps unrelated rows interactive while a model is being verified', async () => {
        let finish!: () => void
        const onVerify = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
        setup({ onVerify })
        const actions = screen.getAllByRole('button', { name: 'model.updateStatus' })
        fireEvent.click(actions[0])
        expect(actions[0]).toBeDisabled()
        expect(actions[1]).not.toBeDisabled()
        await act(async () => { finish() })
        await waitFor(() => expect(actions[0]).not.toBeDisabled())
    })

    it('keeps inherited providers read-only while allowing status inspection', () => {
        setup({ data: { ...provider, is_root_shared_readonly: true, tenant_name: 'Root' } })
        expect(screen.getByRole('button', { name: 'model.modelConfiguration' })).toBeDisabled()
        expect(screen.getAllByRole('switch').every(control => control.hasAttribute('disabled'))).toBe(true)
        expect(screen.getAllByRole('button', { name: 'model.updateStatus' })[0]).not.toBeDisabled()
        expect(screen.getByText('model.tenantSharedReadonly')).toBeVisible()
    })

    it('shows an empty provider and allows collapsing it', () => {
        setup({ data: { ...provider, models: [] } })
        expect(screen.getByText('model.empty')).toBeVisible()
        fireEvent.click(screen.getByRole('button', { name: 'Provider' }))
        expect(screen.queryByText('model.empty')).not.toBeInTheDocument()
    })
})
