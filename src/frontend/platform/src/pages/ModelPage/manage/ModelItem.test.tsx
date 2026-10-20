import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ModelItem, type ModelItemData } from './ModelItem'

vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }))
afterEach(cleanup)
const model: ModelItemData = { id: 1, name: 'model 1', model_name: 'chat', model_type: 'llm', config: { max_tokens: 100, user_kwargs: '{"temperature":0.2}' } }
function setup(data = model) {
    const props = { data, type: 'qwen', onDelete: vi.fn(), onInput: vi.fn(), onConfig: vi.fn() }
    render(<ModelItem {...props} />)
    return props
}

describe('model configuration field migration', () => {
    it('keeps parameter edits local when the dialog is cancelled', () => {
        const props = setup()
        fireEvent.click(screen.getByRole('button', { name: 'model.edit' }))
        fireEvent.change(screen.getByRole('textbox', { name: 'model.pasteAdvancedParamsHere' }), { target: { value: '{"temperature":0.8}' } })
        fireEvent.click(screen.getByRole('button', { name: 'model.cancel' }))
        expect(props.onConfig).not.toHaveBeenCalled()
    })
    it('rejects an array and saves a valid object without dropping other parameters', () => {
        const props = setup()
        fireEvent.click(screen.getByRole('button', { name: 'model.edit' }))
        const field = screen.getByRole('textbox', { name: 'model.pasteAdvancedParamsHere' })
        fireEvent.change(field, { target: { value: '[]' } })
        fireEvent.click(screen.getByRole('button', { name: 'model.save' }))
        expect(props.onConfig).not.toHaveBeenCalled()
        expect(screen.getByText('model.errorInvalidJsonFormat')).toBeVisible()
        fireEvent.change(field, { target: { value: '{"temperature":0.8}' } })
        fireEvent.click(screen.getByRole('button', { name: 'model.save' }))
        expect(props.onConfig).toHaveBeenCalledWith({ max_tokens: 100, user_kwargs: '{"temperature":0.8}' })
    })
    it('clears only the optional token cap and preserves saved advanced parameters', () => {
        const props = setup()
        fireEvent.change(screen.getByRole('spinbutton', { name: 'max_tokens' }), { target: { value: '' } })
        expect(props.onConfig).toHaveBeenCalledWith({ user_kwargs: '{"temperature":0.2}' })
    })
    it('keeps web-search selection in the draft until the provider is saved', () => {
        const props = setup()
        fireEvent.click(screen.getByRole('switch', { name: 'model.webSearch' }))
        expect(props.onConfig).toHaveBeenCalledWith({ ...model.config, enable_web_search: true })
    })
})
