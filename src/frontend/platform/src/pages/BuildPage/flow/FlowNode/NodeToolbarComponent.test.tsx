import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import NodeToolbarComponent from './NodeToolbarComponent'

afterEach(cleanup)
it('renders the installed icons and preserves run, copy and delete actions', () => {
    const onRun = vi.fn()
    const onCopy = vi.fn()
    const onDelete = vi.fn()
    window.addEventListener('nodeCopy', onCopy)
    window.addEventListener('nodeDelete', onDelete)
    try {
        render(<NodeToolbarComponent nodeId="tool_1" type="tool" onRun={onRun} />)
        const buttons = screen.getAllByRole('button')
        buttons.forEach(button => fireEvent.click(button))
        expect(onRun).toHaveBeenCalledTimes(1)
        expect(onCopy.mock.calls[0][0].detail).toEqual(['tool_1'])
        expect(onDelete.mock.calls[0][0].detail).toBe('tool_1')
    } finally {
        window.removeEventListener('nodeCopy', onCopy)
        window.removeEventListener('nodeDelete', onDelete)
    }
})
