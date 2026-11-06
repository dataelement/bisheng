import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { addDepartmentMembersApi } from '@/controllers/API/department'
import { AddMemberDialog } from './AddMemberDialog'

vi.mock('@/components/bs-comp/selectComponent/useSubjectSearch', () => ({ useSubjectSearch: () => ({ rows: [{ user_id: 7, user_name: 'Tester' }], keyword: 'Tester', setKeyword: vi.fn(), status: 'ready', loading: false, hasMore: false }) }))
vi.mock('@/controllers/API/department', () => ({ addDepartmentMembersApi: vi.fn(async () => ({})) }))
vi.mock('@/controllers/request', async (importOriginal) => ({ ...await importOriginal<typeof import('@/controllers/request')>() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it.each([1, 0])('keeps numeric affiliation %s in the member payload', async (affiliation) => {
    const onAdded = vi.fn()
    render(<AddMemberDialog deptId="dept-1" onAdded={onAdded} onClose={vi.fn()} />)
    await userEvent.click(screen.getByText('Tester'))
    if (affiliation === 0) await userEvent.click(screen.getByRole('radio', { name: 'bs:department.secondary' }))
    await userEvent.click(screen.getByRole('button', { name: 'confirmButton' }))
    await waitFor(() => expect(addDepartmentMembersApi).toHaveBeenCalledWith('dept-1', { user_ids: [7], is_primary: affiliation }))
    expect(onAdded).toHaveBeenCalledOnce()
})
