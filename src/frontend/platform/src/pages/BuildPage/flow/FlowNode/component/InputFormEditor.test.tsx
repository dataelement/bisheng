import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { InputFormEditor } from './InputFormEditor'
import { LegacyInputFormEditor } from './LegacyInputFormEditor'
import { FormType, type SerializedInputField } from './inputFormTypes'

vi.mock('./VarInput', () => ({ default: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => <input aria-label="display-name" defaultValue={value} onChange={event => onChange(event.target.value)} /> }))
vi.mock('./DragOptions', () => ({ default: () => null }))
vi.mock('./FileTypeSelect', () => ({ default: () => null }))
vi.mock('@/util/flowUtils', () => ({ isVarInFlow: () => false }))
afterEach(cleanup)
const nodeData = { key: 'input', type: 'input_form', value: [] }
const initialData: SerializedInputField = { type: FormType.File, value: 'Upload', key: 'file', required: true, multiple: true, file_content: 'text', file_type: 'all', file_path: 'paths', file_content_size: 1000, image_file: 'images', file_parse_mode: ['extract_text'] }
it('keeps file strategy changes linked to the visible fields and submitted draft', async () => {
    const onSubmit = vi.fn()
    render(<InputFormEditor nodeId="input_1" nodeData={nodeData} initialData={initialData} onSubmit={onSubmit} onCancel={vi.fn()} existingOptions={[]} />)
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'notParse' }))
    expect(screen.queryByText('parseResultName')).not.toBeInTheDocument()
    expect(screen.getByText('filePathName')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ processingOption: 'no_parse', filepath: 'paths', isMultiple: true })))
})
it('does not submit an empty text field and retains the editable draft', () => {
    const onSubmit = vi.fn()
    render(<InputFormEditor nodeId="input_1" nodeData={nodeData} onSubmit={onSubmit} onCancel={vi.fn()} existingOptions={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('displayNameRequired')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('display-name'), { target: { value: 'Question' } })
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ displayName: 'Question', variableName: 'text_input' }))
})
it('loads and resaves legacy file fields with their original values', () => {
    const onSubmit = vi.fn()
    render(<LegacyInputFormEditor nodeId="input_1" nodeData={nodeData} initialData={initialData} onSubmit={onSubmit} onCancel={vi.fn()} existingOptions={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ displayName: 'Upload', filepath: 'paths', filecontent: 'text' }))
})
