import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { LogPage } from './index'
import type { ContextType } from 'react'
import { locationContext } from '@/contexts/locationContext'
import { userContext } from '@/contexts/userContext'

vi.mock('./systemLog', () => ({ default: () => <div>System panel</div> }))
vi.mock('./useAppLog', () => ({ default: () => <div>Application panel</div> }))
vi.mock('./runtime/RuntimeAuditPanel', () => ({ RuntimeAuditPanel: () => <div>Runtime panel</div> }))
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

it.each([
    { enabled: false, role: 'admin', child: false, visible: false },
    { enabled: true, role: 'user', child: false, visible: false },
    { enabled: true, role: 'admin', child: false, visible: true },
    { enabled: true, role: 'user', child: true, visible: true },
])('gates runtime records for deployment and administrator identity: %j', ({ enabled, role, child, visible }) => {
    const location = { appConfig: { appRuntimeEnabled: enabled } } as unknown as ContextType<typeof locationContext>
    const user = { user: { role, is_child_admin: child } } as unknown as ContextType<typeof userContext>
    render(<locationContext.Provider value={location}><userContext.Provider value={user}><LogPage /></userContext.Provider></locationContext.Provider>)
    const tab = screen.queryByRole('tab', { name: 'log.runtime.title' })
    if (visible) {
        expect(tab).toBeVisible()
        fireEvent.mouseDown(tab!, { button: 0, ctrlKey: false })
        expect(screen.getByText('Runtime panel')).toBeVisible()
    } else expect(tab).not.toBeInTheDocument()
})
