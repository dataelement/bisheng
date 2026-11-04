import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { createContext } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useMemberTableController } from '@/pages/DepartmentPage/components/MemberTable'

const mock = vi.hoisted(() => ({ disable: vi.fn(), notify: vi.fn(), error: vi.fn() }))
vi.mock('@/controllers/API/department', () => ({
    getDepartmentMembersApi: vi.fn(async () => ({ data: [{ user_id: 7, user_name: 'Member', enabled: true }], total: 1 })),
    getDepartmentAdminsApi: vi.fn(async () => []),
    getDepartmentPathTreeApi: vi.fn(), searchGlobalMembersApi: vi.fn(),
}))
vi.mock('@/controllers/API/user', () => ({ disableUserApi: mock.disable }))
vi.mock('@/controllers/request', () => ({ showApiError: mock.error }))
vi.mock('@/contexts/userContext', () => ({ userContext: createContext({ user: {} }) }))
vi.mock('@/pages/DepartmentPage/components/MemberTableView', () => ({ MemberTableView: () => null }))
vi.mock('@bisheng/ui', async (importOriginal) => ({
    ...await importOriginal<typeof import('@bisheng/ui')>(), notification: { open: mock.notify },
}))
beforeEach(() => vi.clearAllMocks())
afterEach(cleanup)

it('rolls back a rejected account toggle without reporting success or refreshing the parent', async () => {
    const error = new Error('Update denied')
    mock.disable.mockRejectedValueOnce(error)
    const onChanged = vi.fn()
    const { result } = renderHook(() => useMemberTableController({ deptId: 'dept-1', deptName: 'Department', onChanged }))
    await waitFor(() => expect(result.current.members).toHaveLength(1))
    act(() => result.current.handleToggleEnabled(result.current.members[0], false))
    await waitFor(() => expect(mock.error).toHaveBeenCalledWith(error))
    expect(result.current.members[0].enabled).toBe(true)
    expect(onChanged).not.toHaveBeenCalled()
    expect(mock.notify).not.toHaveBeenCalled()
})

it('keeps the new account status and reports completion only after a successful write', async () => {
    mock.disable.mockResolvedValueOnce(null)
    const onChanged = vi.fn()
    const { result } = renderHook(() => useMemberTableController({ deptId: 'dept-1', deptName: 'Department', onChanged }))
    await waitFor(() => expect(result.current.members).toHaveLength(1))
    act(() => result.current.handleToggleEnabled(result.current.members[0], false))
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
    expect(result.current.members[0].enabled).toBe(false)
    expect(mock.notify).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
})
