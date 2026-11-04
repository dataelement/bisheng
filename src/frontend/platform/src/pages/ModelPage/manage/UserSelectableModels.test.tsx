import { fireEvent, render, screen } from '@/test/test-utils'
import { expect, it, vi } from 'vitest'
import { UserSelectableModels } from './UserSelectableModels'
import { updateModelMetadata } from './userModelMetadata'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./dsh/ModelVisionSwitch', () => ({ ModelVisionSwitch: () => <span>vision-control</span> }))
vi.mock('./dsh/ModelMultiplierInput', () => ({ ModelMultiplierInput: () => <span>rate-control</span> }))
vi.mock('./dsh/ModelAccessDialog', () => ({ ModelAccessDialog: ({ model }: { model: { name: string } | null }) => model ? <p role="dialog">{model.name}</p> : null }))

it('edits display metadata and opens visibility without a permission summary or default columns', () => {
    const change = vi.fn()
    render(<UserSelectableModels data={[{ id: 1, name: 'Provider A', models: [
        { id: 42, model_name: 'vendor-model', model_type: 'llm', online: true },
        { id: 43, model_name: 'offline', model_type: 'llm', online: false },
    ] }]} configuredModels={[{ id: '42', displayName: 'Display label', description: 'kept' }]}
        enterpriseEnabled disabled={false} onMetadataChange={change} />)
    expect(screen.getByText('Provider A')).toBeVisible()
    expect(screen.queryByText('offline')).toBeNull()
    expect(screen.getAllByRole('columnheader')).toHaveLength(6)
    const input = screen.getByRole('textbox', { name: 'model.displayName · vendor-model' })
    expect(input).toHaveValue('Display label')
    fireEvent.change(input, { target: { value: 'Renamed' } })
    expect(change).toHaveBeenCalledWith(expect.objectContaining({ id: 42 }), { displayName: 'Renamed' })
    fireEvent.click(screen.getByRole('button', { name: 'model.configureVisibility' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Display label')
    expect(screen.queryByText('kept')).toBeNull()
})

it('preserves hidden descriptions and offline rows while adding a desktop-only model label', () => {
    const original = [{ id: '1', displayName: 'Existing', description: 'Keep this', visual: true }]
    const renamed = updateModelMetadata(original, { id: 1, model_name: 'vendor' }, { displayName: 'New' })
    expect(renamed).toEqual([{ ...original[0], displayName: 'New' }])
    const added = updateModelMetadata(renamed, { id: 2, model_name: 'desktop-only' }, { displayName: 'Desktop label' })
    expect(added[0]).toEqual(renamed[0])
    expect(added[1]).toEqual({ id: '2', key: '2', name: 'desktop-only', displayName: 'Desktop label' })
    expect(original[0].displayName).toBe('Existing')
})
