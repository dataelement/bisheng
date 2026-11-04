import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import InputFormItem from './InputFormItem'
import LegacyInputFormItem from './InputFormItemOld'
import { FormOption, FormType, type InputFormDraft } from './inputFormTypes'

const fixture = vi.hoisted(() => ({ draft: {} as InputFormDraft }))
vi.mock('./InputFormEditor', () => ({ InputFormEditor: ({ onSubmit }: { onSubmit: (draft: InputFormDraft) => void }) => <button onClick={() => onSubmit(fixture.draft)}>Save draft</button> }))
vi.mock('./LegacyInputFormEditor', () => ({ LegacyInputFormEditor: ({ onSubmit }: { onSubmit: (draft: InputFormDraft) => void }) => <button onClick={() => onSubmit(fixture.draft)}>Save legacy draft</button> }))
vi.mock('./DragOptions', () => ({ default: () => null }))
vi.mock('../../flowStore', () => ({ default: () => ({ flow: { nodes: [], edges: [] } }) }))
vi.mock('@/util/flowUtils', () => ({ isVarInFlow: () => false }))
afterEach(cleanup)
function draft(processingOption: FormOption): InputFormDraft {
    return { formType: FormType.File, displayName: 'Upload', variableName: 'upload', filecontent: 'parsed_text', filepath: 'file_path', fileType: 'all', fileContentSize: 15000, imageFile: 'images', isMultiple: true, isRequired: true, allowMultiple: false, options: [], processingOption }
}
function renderItem(legacy = false) {
    const onChange = vi.fn(); const Component = legacy ? LegacyInputFormItem : InputFormItem
    render(<Component nodeId="input_1" data={{ key: 'input', value: [] }} onChange={onChange} onValidate={vi.fn()} onVarEvent={vi.fn()} i18nPrefix="form." />)
    fireEvent.click(screen.getByRole('button', { name: 'form.label' }))
    fireEvent.click(screen.getByRole('button', { name: legacy ? 'Save legacy draft' : 'Save draft' }))
    return onChange.mock.calls[0][0]
}
it('stores parse-only files without temporary knowledge ingestion', () => {
    fixture.draft = draft(FormOption.ParseOnly)
    const value = renderItem()
    expect(value[0]).toMatchObject({ type: 'file', file_parse_mode: ['extract_text'], file_content: 'parsed_text', file_path: 'file_path', multiple: true })
    expect(value[0].key).not.toBe('upload')
})
it('preserves the knowledge variable name when parsing and ingesting', () => {
    fixture.draft = draft(FormOption.ParseIngest)
    expect(renderItem()[0]).toMatchObject({ key: 'upload', file_parse_mode: ['extract_text', 'ingest_to_temp_kb'] })
})
it('stores raw files without parsing or ingestion', () => {
    fixture.draft = draft(FormOption.NoParse)
    expect(renderItem()[0]).toMatchObject({ file_parse_mode: ['keep_raw'], file_path: 'file_path', image_file: 'images' })
})
it('preserves the legacy file schema without adding the v3 strategy field', () => {
    fixture.draft = draft(FormOption.ParseOnly)
    const value = renderItem(true)
    expect(value[0]).toMatchObject({ key: 'upload', type: 'file', file_content: 'parsed_text', multiple: true })
    expect(value[0]).not.toHaveProperty('file_parse_mode')
})
