import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import {
    getDshModelSubjects,
    getDshModelUserPermissions,
    saveDshSubjectPolicy,
    saveDshPolicy,
} from '@/controllers/API/dsh'
import { ModelAccessDialog } from './ModelAccessDialog'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/components/bs-icons/loading/Load.svg?react', () => ({ default: () => <svg /> }))
vi.mock('@/controllers/API/dsh', () => ({
    getDshModelSubjects: vi.fn(),
    getDshModelUserPermissions: vi.fn(),
    saveDshSubjectPolicy: vi.fn(),
    getDshOperation: vi.fn(),
    saveDshPolicy: vi.fn(),
    isDshRequestRejected: () => false,
    isDshSeatLimitReached: () => false,
}))
const model = { id: 7, name: 'Model' }
const department = {
    subject_type: 'DEPARTMENT' as const,
    subject_id: 31,
    name: 'Organization',
    parent_id: null,
    depth: 0,
    version: 1,
    enabled: true,
    monthly_token_limit: 100000,
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getDshModelSubjects).mockResolvedValue({
        tenant_id: 2,
        model_id: 7,
        departments: [department],
        roles: [],
    })
    vi.mocked(getDshModelUserPermissions).mockImplementation(async (_id, query) => ({
        tenant_id: 2,
        model: { ...model, is_root_shared: false },
        next_cursor: null,
        has_more: false,
        items: query.unassigned_only
            ? []
            : [
                  {
                      user_id: 20,
                      user_name: 'Alice',
                      direct_version: vi.mocked(saveDshPolicy).mock.calls.length ? 1 : 0,
                      direct_enabled: vi.mocked(saveDshPolicy).mock.calls.length > 0,
                      direct_monthly_token_limit: 0,
                      direct_pending_operation_id: null,
                      departments: [{ id: 31, name: 'Organization', is_primary: true }],
                      roles: [],
                      authorized: true,
                      monthly_token_limit: 100000,
                      access_status: 'PENDING_LOGIN',
                      sources: [],
                      department_match: 'DIRECT',
                  },
              ],
    }))
    vi.mocked(saveDshSubjectPolicy).mockImplementation(async (_id, _type, _subject, _tenant, input) => ({
        ...department,
        ...input,
        version: 2,
    }))
})

it('separates the selected department default from member effective quotas', async () => {
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    expect(await screen.findByText('Alice')).toBeTruthy()
    expect(screen.getByRole('navigation', { name: 'dsh.quotaDepartments' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Organization' })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByText('dsh.departmentDefaultQuota')).toBeTruthy()
    expect(screen.getByText('dsh.wanPerPersonMonth')).toBeTruthy()
    expect(screen.queryByLabelText('Organization · dsh.configuredQuotaWan')).toBeNull()
    expect(screen.queryByLabelText('Alice · dsh.configuredQuotaWan')).toBeNull()
})

it('opens the department editor and saves the staged quota', async () => {
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Organization · dsh.editQuota' }))
    fireEvent.change(screen.getByLabelText('Organization · dsh.configuredQuotaWan'), { target: { value: '0.6' } })
    expect(saveDshSubjectPolicy).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    await waitFor(() => expect(saveDshSubjectPolicy).toHaveBeenCalledWith(7, 'DEPARTMENT', 31, 2, {
        expected_version: 1, enabled: true, monthly_token_limit: 6000,
    }))
    await waitFor(() => expect(screen.queryByLabelText('Organization · dsh.configuredQuotaWan')).toBeNull())
})

it('selects another department and fetches its direct members', async () => {
    vi.mocked(getDshModelSubjects).mockResolvedValue({ tenant_id: 2, model_id: 7, roles: [], departments: [department, { ...department, subject_id: 32, parent_id: 31, name: 'Child' }] })
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Child' }))
    await waitFor(() => expect(getDshModelUserPermissions).toHaveBeenCalledWith(7, expect.objectContaining({ department_id: 32, membership: 'DIRECT' }), expect.any(AbortSignal)))
    expect(screen.getByRole('heading', { name: 'Child' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unassignedDepartment' }))
    await waitFor(() => expect(getDshModelUserPermissions).toHaveBeenCalledWith(7, expect.objectContaining({ unassigned_only: true }), expect.any(AbortSignal)))
    expect(screen.queryByText('dsh.departmentDefaultQuota')).toBeNull()
})

it('searches users across departments and shows their department names', async () => {
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    await screen.findByText('Alice')
    fireEvent.change(screen.getByLabelText('dsh.searchUsername'), { target: { value: 'Alice' } })
    await waitFor(() => expect(getDshModelUserPermissions).toHaveBeenCalledWith(7, expect.objectContaining({ keyword: 'Alice', department_id: undefined }), expect.any(AbortSignal)))
    expect(screen.getByRole('heading', { name: 'dsh.quotaSearchResults' })).toBeTruthy()
    expect(await screen.findByText('Alice')).toBeTruthy()
    expect(screen.getAllByText('Organization').length).toBeGreaterThan(0)
    expect(screen.queryByText(/ID: 20/)).toBeNull()
})

it('expands a member editor and saves an explicit zero override', async () => {
    vi.mocked(saveDshPolicy).mockImplementation(async (_user, _model, _tenant, input) => ({ operation_id: input.operation_id, status: 'SUCCEEDED' }) as Awaited<ReturnType<typeof saveDshPolicy>>)
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice · dsh.editQuota' }))
    fireEvent.change(screen.getByLabelText('Alice · dsh.configuredQuotaWan'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledWith('20', 7, '2', expect.objectContaining({ enabled: true, monthly_token_limit: 0 })))
    await waitFor(() => expect(screen.queryByLabelText('Alice · dsh.configuredQuotaWan')).toBeNull())
})

it('previews department changes for default members and preserves individual overrides', async () => {
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    await screen.findByText('Alice')
    fireEvent.click(screen.getByRole('button', { name: 'Organization · dsh.editQuota' }))
    fireEvent.change(screen.getByLabelText('Organization · dsh.configuredQuotaWan'), { target: { value: '20' } })
    expect(screen.getByText('20')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Alice · dsh.editQuota' }))
    const input = screen.getByLabelText('Alice · dsh.configuredQuotaWan')
    expect(input).toHaveValue('20')
    fireEvent.change(input, { target: { value: '5' } })
    expect(screen.getByText('dsh.individualQuota')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Organization · dsh.configuredQuotaWan'), { target: { value: '30' } })
    expect(input).toHaveValue('5')
    fireEvent.click(screen.getByRole('button', { name: 'dsh.useDepartmentQuota' }))
    expect(screen.getByText('30')).toBeTruthy()
    expect(screen.queryByText('dsh.individualQuota')).toBeNull()
})

it('keeps the department editor open when saving fails', async () => {
    vi.mocked(saveDshSubjectPolicy).mockRejectedValue(new Error('failed'))
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Organization · dsh.editQuota' }))
    fireEvent.change(screen.getByLabelText('Organization · dsh.configuredQuotaWan'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Organization · dsh.configuredQuotaWan')).toHaveValue('20')
})
