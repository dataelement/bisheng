import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { PopUpContext } from '@/contexts/popUpContext'
import { TypeModal } from '@/utils'
import PromptAreaComponent from './PromptCom'

vi.mock('@/modals/genericModal', () => ({ default: () => null }))
afterEach(cleanup)
it('opens the expanded editor and keeps saving the prompt through the original callback', () => {
    const openPopUp = vi.fn()
    const onChange = vi.fn()
    render(<PopUpContext.Provider value={{ openPopUp, closePopUp: vi.fn(), closeEdit: "", setCloseEdit: vi.fn() }}>
        <PromptAreaComponent field_name="prompt" value="Original prompt" type={TypeModal.TEXT} onChange={onChange} disabled={false} />
    </PopUpContext.Provider>)
    fireEvent.click(screen.getByRole('button', { name: 'evaluation.editPrompt' }))
    const modal = openPopUp.mock.calls[0][0] as ReactElement<{ setValue: (value: string) => void; field_name: string; value: string }>
    expect(modal.props.field_name).toBe('prompt')
    expect(modal.props.value).toBe('Original prompt')
    act(() => modal.props.setValue('Revised prompt'))
    expect(onChange).toHaveBeenCalledWith('Revised prompt')
    expect(screen.getByText('Revised prompt')).toBeInTheDocument()
})
