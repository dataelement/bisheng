import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
                      direct_version: 0,
                      direct_enabled: false,
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

it('uses one expanded department tree and shows confirmed effective quota and login eligibility', async () => {
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    expect(await screen.findByText('Alice')).toBeTruthy()
    expect(screen.queryByRole('tab')).toBeNull()
    expect(screen.getByText('dsh.access_PENDING_LOGIN')).toBeTruthy()
    expect(screen.getAllByText('10')).toHaveLength(2)
    expect(screen.getByLabelText('Organization · dsh.configuredQuotaWan')).toHaveValue('10')
    expect(screen.getByText('dsh.authorizationAndStatus')).toBeTruthy()
    expect(screen.getByText('ID: 20')).toBeTruthy()
})

it('keeps department changes as drafts and saves empty as zero', async () => {
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    const input = await screen.findByLabelText('Organization · dsh.configuredQuotaWan')
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)
    expect(saveDshSubjectPolicy).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    await waitFor(() =>
        expect(saveDshSubjectPolicy).toHaveBeenCalledWith(7, 'DEPARTMENT', 31, 2, {
            expected_version: 1,
            enabled: false,
            monthly_token_limit: 0,
        }),
    )
})

it('saves a personal quota from the tree only after the unified save action', async () => {
    vi.mocked(saveDshPolicy).mockImplementation(async (_user, _model, _tenant, input) => ({
        operation_id: input.operation_id,
        status: 'SUCCEEDED',
        tenant_id: 2,
        user_id: 20,
        actor_user_id: 90,
        action: 'USER_POLICY_UPDATE',
        before_values: null,
        after_values: null,
        expected_grant_version: null,
        expected_policy_version: 0,
        committed_at: null,
        effective_at: null,
        result_code: null,
        result_payload: null,
    }))
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    const input = await screen.findByLabelText('Alice · dsh.configuredQuotaWan')
    fireEvent.change(input, { target: { value: '100' } })
    fireEvent.blur(input)
    expect(saveDshPolicy).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    await waitFor(() =>
        expect(saveDshPolicy).toHaveBeenCalledWith(
            '20',
            7,
            '2',
            expect.objectContaining({
                expected_version: 0,
                enabled: true,
                monthly_token_limit: 1000000,
            }),
        ),
    )
})

it('saves fractional wan quotas as exact integer Tokens', async () => {
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    const input = await screen.findByLabelText('Organization · dsh.configuredQuotaWan')
    fireEvent.change(input, { target: { value: '0.6' } })
    expect(input).toHaveValue('0.6')
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    await waitFor(() =>
        expect(saveDshSubjectPolicy).toHaveBeenCalledWith(7, 'DEPARTMENT', 31, 2, {
            expected_version: 1,
            enabled: true,
            monthly_token_limit: 6000,
        }),
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'save' })).toBeDisabled())
    expect(input).toHaveValue('0.6')
})

it('uses saved ancestor quota for department status until Save succeeds', async () => {
    vi.mocked(getDshModelSubjects).mockResolvedValue({
        tenant_id: 2,
        model_id: 7,
        roles: [],
        departments: [
            department,
            {
                ...department,
                subject_id: 32,
                parent_id: 31,
                name: 'Child',
                enabled: false,
                monthly_token_limit: 0,
            },
        ],
    })
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    const child = await screen.findByRole('button', { name: 'Child' })
    const row = within(child.parentElement!.parentElement!)
    expect(row.getByText('10')).toBeTruthy()
    expect(row.getByText('dsh.access_AUTHORIZED')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Organization · dsh.configuredQuotaWan'), {
        target: { value: '' },
    })
    expect(row.getByText('dsh.access_AUTHORIZED')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    expect(await row.findByText('dsh.access_UNAUTHORIZED')).toBeTruthy()
    expect(row.getByText('0')).toBeTruthy()
})

it('renders empty department branches without member placeholders', async () => {
    vi.mocked(getDshModelUserPermissions).mockResolvedValue({
        tenant_id: 2,
        model: { ...model, is_root_shared: false },
        next_cursor: null,
        has_more: false,
        items: [],
    })
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    await screen.findByRole('button', { name: 'Organization' })
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unassignedDepartment' }))
    await waitFor(() =>
        expect(getDshModelUserPermissions).toHaveBeenCalledWith(
            7,
            expect.objectContaining({ unassigned_only: true }),
            expect.any(AbortSignal),
        ),
    )
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
    expect(screen.queryByText('dsh.noDirectMembers')).toBeNull()
})

it('uses the same search to find a user and preserves the department path', async () => {
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    await screen.findByText('Alice')
    fireEvent.change(screen.getByLabelText('dsh.searchDepartmentsAndUsers'), { target: { value: 'Alice' } })
    await waitFor(() =>
        expect(getDshModelUserPermissions).toHaveBeenCalledWith(
            7,
            expect.objectContaining({
                keyword: 'Alice',
                include_seats: true,
            }),
            expect.any(AbortSignal),
        ),
    )
    expect(await screen.findByText('Alice')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Organization' })).toBeTruthy()
})
