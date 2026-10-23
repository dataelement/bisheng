import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import TextInput from './textInput'

vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))
afterEach(cleanup)
it('retains a rejected version-name edit and lets the user retry', async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error('Rename failed')).mockResolvedValue(undefined)
    render(<TextInput value="v1" onSave={onSave} />)
    fireEvent.doubleClick(screen.getByText('v1'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Release draft' } })
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('textbox')).toHaveValue('Release draft')
    await waitFor(() => expect(screen.getByRole('textbox')).toBeEnabled())
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
    await waitFor(() => expect(screen.queryByRole('textbox')).not.toBeInTheDocument())
    expect(onSave).toHaveBeenCalledTimes(2)
})
