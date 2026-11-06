import { Dialog } from '@/components/bs-ui/dialog'
import { cleanup,fireEvent,render,screen } from '@testing-library/react'
import { afterEach,expect,it,vi } from 'vitest'
import CodeExecutor from './CodeExecutor'
import Dalle3 from './Dalle3'

afterEach(cleanup)
it('changes sandbox execution mode without erasing saved provider settings', () => {
    const onSubmit = vi.fn()
    render(<Dialog open><CodeExecutor formData={{ type: 'e2b', config: { e2b: { type: 'official' }, official: { api_key: 'fixture-key' } } }} onSubmit={onSubmit} /></Dialog>)
    fireEvent.click(screen.getByRole('radio', { name: /executionContainerLabel/ }))
    expect(screen.getByRole('radio', { name: /executionContainerLabel/ })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ type: 'container', config: expect.objectContaining({ official: { api_key: 'fixture-key' }, container: {} }) }))
})
it('switches image providers and preserves provider-specific form visibility', () => {
    render(<Dialog open><Dalle3 formData={{ openai_api_key: 'fixture-key' }} onSubmit={vi.fn()} /></Dialog>)
    fireEvent.click(screen.getByRole('radio', { name: 'Azure' }))
    expect(screen.getByRole('radio', { name: 'Azure' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByLabelText(/Deployment Name/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'OpenAI' }))
    expect(screen.queryByLabelText(/Deployment Name/)).not.toBeInTheDocument()
})
