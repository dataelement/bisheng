import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import NodeTabs from './NodeTabs'

afterEach(cleanup)
it('preserves the selected node mode and emits the next mode only on selection', () => {
    const onChange = vi.fn()
    render(<NodeTabs data={{ type: 'input', tab: { value: 'dialog_input', options: [{ key: 'dialog_input' }, { key: 'form', help: 'Form help' }] } }} onChange={onChange} />)
    expect(screen.getByRole('tab', { name: 'node.input.tab_dialog_input.label' })).toHaveAttribute('aria-selected', 'true')
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'node.input.tab_form.label' }), { button: 0, ctrlKey: false })
    expect(onChange).toHaveBeenLastCalledWith('form')
})
