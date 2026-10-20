import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { useMemberTableController } from './MemberTable'
import { MemberTableView } from './MemberTableView'

vi.mock('@/pages/LoginPage/UserPwdModal', () => ({ default: () => null }))
vi.mock('./CreateLocalMemberDialog', () => ({ CreateLocalMemberDialog: () => null }))
vi.mock('./OrganizationMemberEditDialog', () => ({ OrganizationMemberEditDialog: () => null }))
afterEach(cleanup)
it('shows inherited administrator source on hover and keyboard focus', async () => {
    // Isolate presentation from member requests; only the empty-list fields are read.
    const controller = { memberScope: 'dept', keyword: '', isPrimaryFilter: 'all', isArchived: false,
        t: (key: string) => key, directAdmins: [], inheritedAdmins: [{ user_id: 7, user_name: 'Inherited admin', sourceDeptName: 'Parent' }],
        members: [], page: 1, total: 0, globalRows: [], globalTotal: 0, user: {},
        mrc: { totalWidth: 800, getThProps: () => ({}), getTdProps: () => ({}), startResize: vi.fn() },
    } as unknown as ReturnType<typeof useMemberTableController>
    render(<MemberTableView controller={controller} />)
    const name = screen.getByText('Inherited admin')
    const user = userEvent.setup()
    await user.hover(name)
    expect(await screen.findByRole('tooltip', { name: 'bs:department.inheritedAdminSource' })).toBeVisible()
    await user.unhover(name)
    const trigger = name.closest<HTMLElement>('[tabindex="0"]')
    expect(trigger).not.toBeNull()
    trigger!.focus()
    expect(await screen.findByRole('tooltip', { name: 'bs:department.inheritedAdminSource' })).toBeVisible()
})
