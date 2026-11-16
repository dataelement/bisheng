import { Dialog } from '@/components/bs-ui/dialog'
import { cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react'
import { afterEach,expect,it,vi } from 'vitest'
import CodeExecutor from './CodeExecutor'
import ImageGeneration from './ImageGeneration'

afterEach(cleanup)
it('changes sandbox execution mode without erasing saved provider settings', () => {
    const onSubmit = vi.fn()
    render(<Dialog open><CodeExecutor formData={{ type: 'e2b', config: { e2b: { type: 'official' }, official: { api_key: 'fixture-key' } } }} onSubmit={onSubmit} /></Dialog>)
    fireEvent.click(screen.getByRole('radio', { name: /executionContainerLabel/ }))
    expect(screen.getByRole('radio', { name: /executionContainerLabel/ })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ type: 'container', config: expect.objectContaining({ official: { api_key: 'fixture-key' }, container: {} }) }))
})
it('saves a configurable image model without Azure fields', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<Dialog open><ImageGeneration formData={{ openai_api_key: '********' }} onSubmit={onSubmit} /></Dialog>)
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/imageGeneration.model/), { target: { value: 'custom-image-model' } })
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ provider: 'openai', openai_api_base: 'https://api.openai.com/v1', openai_api_key: '********', model: 'custom-image-model', openai_proxy: '' }))
})
it('retains the image draft after a failed save', async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error('save failed'))
    render(<Dialog open><ImageGeneration formData={{ openai_api_key: '********', model: 'selected-model' }} onSubmit={onSubmit} /></Dialog>)
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.getByRole('button', { name: 'confirm' })).not.toBeDisabled())
    expect(screen.getByLabelText(/imageGeneration.model/)).toHaveValue('selected-model')
})
