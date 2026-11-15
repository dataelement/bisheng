import { useContext, type ReactNode } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { locationContext } from '@/contexts/locationContext'
import { userContext } from '@/contexts/userContext'
import SystemPage from './index'

vi.mock('./components/OrganizationAndMembers', () => ({ default: () => <div>Organization content</div> }))
vi.mock('./components/Users', () => ({ default: () => <div>User content</div> }))
vi.mock('./components/UserGroup', () => ({ default: () => <div>Groups content</div> }))
vi.mock('./components/RolesAndPermissions', () => ({ RolesAndPermissions: () => <div>Roles content</div> }))
vi.mock('./components/OrgSync', () => ({ default: () => <div>Sync content</div> }))
vi.mock('./components/PersonalToken', () => ({ PersonalToken: () => <div>Tokens content</div> }))
vi.mock('./components/ServiceAccount', () => ({ ServiceAccount: () => <div>Accounts content</div> }))
vi.mock('./components/Config', () => ({ default: () => <div>Configuration content</div> }))
vi.mock('./theme', () => ({ default: () => <div>Theme content</div> }))

interface FixtureProps {
    user: Record<string, unknown>
    apiEnabled?: boolean
    children: ReactNode
}
function Fixture({ user, apiEnabled = false, children }: FixtureProps) {
    const location = useContext(locationContext)
    const currentUser = useContext(userContext)
    return <locationContext.Provider value={{ ...location, appConfig: { ...location.appConfig, openApiManagementEnabled: apiEnabled } }}>
        <userContext.Provider value={{ ...currentUser, user }}>{children}</userContext.Provider>
    </locationContext.Provider>
}
afterEach(cleanup)

it('keeps administrator navigation and switches real shared tabs', async () => {
    render(<Fixture user={{ role: 'admin' }} apiEnabled><SystemPage /></Fixture>)
    expect(screen.getAllByRole('tab')).toHaveLength(9)
    expect(screen.getByRole('tab', { name: 'system.inviteCode.tab' })).toBeInTheDocument()
    expect(screen.getByText('Organization content')).toBeVisible()
    await userEvent.click(screen.getByRole('tab', { name: 'openApiManagement.serviceAccount.title' }))
    expect(screen.getByText('Accounts content')).toBeVisible()
    expect(screen.queryByText('Organization content')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'system.appearanceSettings' }))
    expect(screen.getByText('Theme content')).toBeVisible()
})
it('keeps instance settings hidden for child administrators', () => {
    render(<Fixture user={{ role: 'user', is_child_admin: true }} apiEnabled><SystemPage /></Fixture>)
    expect(screen.getAllByRole('tab')).toHaveLength(5)
    expect(screen.queryByRole('tab', { name: 'system.systemConfiguration' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'orgSync:title' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'system.appearanceSettings' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'system.inviteCode.tab' })).not.toBeInTheDocument()
})
it('respects the deployment flag and the legacy user-only entry', () => {
    render(<Fixture user={{ role: 'user' }}><SystemPage /></Fixture>)
    expect(screen.getAllByRole('tab')).toHaveLength(1)
    expect(screen.getByText('User content')).toBeVisible()
    expect(screen.queryByRole('tab', { name: 'openApiManagement.personalToken.title' })).not.toBeInTheDocument()
})
