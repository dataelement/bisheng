import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { EnumMultiSelect } from './EnumMultiSelect'

const enums = vi.hoisted(() => vi.fn())
vi.mock('@/controllers/API/dashboard', () => ({ getFieldEnums: enums }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
function Picker() {
    const [selected, setSelected] = useState<string[]>([])
    return <><EnumMultiSelect dataset_code="dataset-1" fieldCode="country" selected={selected} onChange={setSelected} placeholder="Choose values" /><output aria-label="selected">{JSON.stringify(selected)}</output></>
}
it('keeps single/select-all selection and shared-tag removal without double toggles', async () => {
    enums.mockResolvedValue({ enums: ['Alpha', 'Beta'] })
    render(<Picker />)
    fireEvent.click(screen.getByText('Choose values'))
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Alpha' }))
    expect(screen.getByLabelText('selected')).toHaveTextContent('["Alpha"]')
    fireEvent.click(screen.getByRole('checkbox', { name: 'chartSelector.selectAll' }))
    expect(screen.getByLabelText('selected')).toHaveTextContent('["Alpha","Beta"]')
    fireEvent.click(screen.getAllByRole('button', { name: 'removeSelectedValue' })[0])
    expect(screen.getByLabelText('selected')).toHaveTextContent('["Beta"]')
})
it('searches the existing field endpoint and keeps clearing/reopening usable', async () => {
    enums.mockImplementation(({ keyword }: { keyword: string }) => Promise.resolve({ enums: keyword ? ['Alpha'] : ['Alpha', 'Beta'] }))
    render(<Picker />)
    fireEvent.click(screen.getByText('Choose values'))
    await screen.findByRole('checkbox', { name: 'Beta' })
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Al' } })
    await waitFor(() => expect(enums).toHaveBeenLastCalledWith(expect.objectContaining({ field: 'country', dataset_code: 'dataset-1', keyword: 'Al' })))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '' } })
    await screen.findByRole('checkbox', { name: 'Beta' })
    expect(screen.getByRole('textbox')).toHaveValue('')
})
