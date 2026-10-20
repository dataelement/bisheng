import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import LogPage from './index'

vi.mock('./systemLog', () => ({ default: () => <div>System panel</div> }))
vi.mock('./useAppLog', () => ({ default: () => <div>Application panel</div> }))
afterEach(cleanup)
it('preserves default application logs and switches the mounted panel with the shared tabs', () => {
    render(<LogPage />)
    expect(screen.getByText('Application panel')).toBeVisible()
    expect(screen.queryByText('System panel')).not.toBeInTheDocument()
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'log.systemOperations' }), { button: 0, ctrlKey: false })
    expect(screen.getByText('System panel')).toBeVisible()
    expect(screen.queryByText('Application panel')).not.toBeInTheDocument()
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'log.appUsage' }), { button: 0, ctrlKey: false })
    expect(screen.getByText('Application panel')).toBeVisible()
})
