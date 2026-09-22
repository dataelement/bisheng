import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
    getDshModelUsers,
    getDshOperation,
    getDshModelPolicy,
    getDshModelSubjects,
    getDshModelUserPermissions,
    saveDshPolicy,
    saveDshSubjectPolicy,
} from '@/controllers/API/dsh'
import type {
    DshModelAccessPage,
    DshModelAccessUser,
    DshModelUserPermissionPage,
    DshOperation,
    DshOperationRef,
    DshSubjectPolicyInventory,
} from '@/types/dsh'
import { ModelAccessRow } from './ModelAccessRow'
import { ModelAccessDialog } from './ModelAccessDialog'

vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }))
vi.mock('@/components/bs-icons/loading/Load.svg?react', () => ({ default: () => <svg /> }))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: { name?: string }) => (options?.name ? `${key}: ${options.name}` : key),
    }),
}))
vi.mock('@/controllers/API/dsh', () => ({
    getDshModelUsers: vi.fn(),
    getDshOperation: vi.fn(),
    getDshModelPolicy: vi.fn(),
    saveDshPolicy: vi.fn(),
    getDshModelSubjects: vi.fn(),
    getDshModelUserPermissions: vi.fn(),
    saveDshSubjectPolicy: vi.fn(),
    isDshRequestRejected: (error: Error) => error.message === 'rejected',
    isDshSeatLimitReached: () => false,
}))
const user: DshModelAccessUser = {
    user_id: 20,
    user_name: 'Before first login',
    version: 3,
    enabled: false,
    monthly_token_limit: 0,
    pending_operation_id: null,
}
const model = { id: 7, name: 'qwen-max' }
const page: DshModelAccessPage = {
    model: { ...model, is_root_shared: true },
    tenant_id: 2,
    items: [user],
    next_cursor: null,
    has_more: false,
}
const subjects: DshSubjectPolicyInventory = {
    tenant_id: 2,
    model_id: 7,
    departments: [
        {
            subject_type: 'DEPARTMENT',
            subject_id: 31,
            name: 'Root Organization',
            parent_id: null,
            depth: 0,
            version: 0,
            enabled: false,
            monthly_token_limit: 0,
        },
        {
            subject_type: 'DEPARTMENT',
            subject_id: 32,
            name: 'Digital Department',
            parent_id: 31,
            depth: 1,
            version: 0,
            enabled: false,
            monthly_token_limit: 0,
        },
    ],
    roles: [
        {
            subject_type: 'ROLE',
            subject_id: 41,
            name: 'Product Manager',
            role_type: 'tenant',
            department_id: null,
            version: 2,
            enabled: true,
            monthly_token_limit: 500,
        },
    ],
}
const permissionPage: DshModelUserPermissionPage = {
    tenant_id: 2,
    model: { ...model, is_root_shared: true },
    items: [
        {
            user_id: 1,
            user_name: 'admin',
            direct_version: 0,
            direct_enabled: false,
            direct_monthly_token_limit: 0,
            direct_pending_operation_id: null,
            departments: [{ id: 32, name: 'Digital Department', is_primary: true }],
            roles: [{ id: 41, name: 'Product Manager' }],
            authorized: true,
            monthly_token_limit: 500,
            department_match: 'DESCENDANT',
            sources: [
                {
                    subject_type: 'ROLE',
                    subject_id: 41,
                    name: 'Product Manager',
                    monthly_token_limit: 500,
                    inherited: false,
                    winning: true,
                },
            ],
        },
    ],
    next_cursor: null,
    has_more: false,
}
function renderRow(overrides: Partial<DshModelAccessUser> = {}) {
    const onOperation = vi.fn()
    render(
        <table>
            <tbody>
                <ModelAccessRow
                    user={{ ...user, ...overrides }}
                    modelId={7}
                    tenantId={2}
                    operations={{}}
                    onOperation={onOperation}
                />
            </tbody>
        </table>,
    )
    return onOperation
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getDshModelUsers).mockResolvedValue(page)
    vi.mocked(getDshOperation).mockRejectedValue(new Error('Unavailable'))
    vi.mocked(saveDshPolicy).mockRejectedValue(new Error('Timeout'))
    vi.mocked(getDshModelSubjects).mockResolvedValue(subjects)
    vi.mocked(getDshModelUserPermissions).mockResolvedValue(permissionPage)
    vi.mocked(saveDshSubjectPolicy).mockImplementation(
        async (_modelId, subjectType, subjectId, _tenantId, body) => ({
            subject_type: subjectType,
            subject_id: subjectId,
            name:
                subjectType === 'DEPARTMENT'
                    ? subjectId === 31
                        ? 'Root Organization'
                        : 'Digital Department'
                    : 'Product Manager',
            version: body.expected_version + 1,
            enabled: body.enabled,
            monthly_token_limit: body.monthly_token_limit,
        }),
    )
})
afterEach(() => vi.unstubAllGlobals())
describe('model-scoped authorization', () => {
    it.each(['HTTP', 'HTTPS'])(
        'grants a model over %s and retries with the original operation ID',
        async (protocol) => {
            if (protocol === 'HTTP') {
                vi.stubGlobal('crypto', {
                    getRandomValues: crypto.getRandomValues.bind(crypto),
                })
                expect(crypto.randomUUID).toBeUndefined()
            }
            const onOperation = renderRow()
            fireEvent.click(screen.getByRole('checkbox'))
            fireEvent.change(screen.getByRole('textbox'), {
                target: { value: '200' },
            })
            fireEvent.click(screen.getByText('dsh.save'))
            await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledTimes(1))
            const body = vi.mocked(saveDshPolicy).mock.calls[0][3]
            expect(body.operation_id).toMatch(
                /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
            )
            expect(body).toEqual({
                operation_id: expect.any(String),
                expected_version: 3,
                enabled: true,
                monthly_token_limit: 200,
            })
            expect(vi.mocked(saveDshPolicy).mock.calls[0].slice(0, 3)).toEqual(['20', 7, '2'])
            expect(screen.getByRole('textbox')).toHaveValue('200')
            fireEvent.click(screen.getByText('dsh.save'))
            expect(saveDshPolicy).toHaveBeenCalledTimes(1)
            const reference = onOperation.mock.calls[0][1] as DshOperationRef
            await act(async () => {
                await reference.retry?.()
            })
            expect(vi.mocked(saveDshPolicy).mock.calls[1][3]).toEqual(body)
        },
    )
    it('revokes only this model using a single-model request', async () => {
        renderRow({
            enabled: true,
            monthly_token_limit: 100,
        })
        fireEvent.click(screen.getByRole('checkbox'))
        fireEvent.click(screen.getByText('dsh.save'))
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalled())
        expect(vi.mocked(saveDshPolicy).mock.calls[0][3]).toMatchObject({
            enabled: false,
            monthly_token_limit: 0,
        })
    })
    it('restores an in-progress operation on reopening and blocks a new save', () => {
        const onOperation = renderRow({ pending_operation_id: 'pending-op' })
        expect(onOperation).toHaveBeenCalledWith(20, {
            operation_id: 'pending-op',
            tenant_id: '2',
            model_id: 7,
        })
        expect(screen.getByRole('checkbox')).toBeDisabled()
        fireEvent.click(screen.getByText('dsh.save'))
        expect(saveDshPolicy).not.toHaveBeenCalled()
    })
    it('requires refresh after a conflict instead of silently overwriting', async () => {
        vi.mocked(saveDshPolicy).mockRejectedValue(new Error('rejected'))
        renderRow()
        fireEvent.click(screen.getByRole('checkbox'))
        fireEvent.click(screen.getByText('dsh.save'))
        await screen.findByText('dsh.rejected')
        expect(screen.getByRole('checkbox')).toBeDisabled()
        fireEvent.click(screen.getByText('dsh.save'))
        expect(saveDshPolicy).toHaveBeenCalledTimes(1)
        expect(getDshModelPolicy).not.toHaveBeenCalled()
    })
    it('unblocks refresh when a retry from a previously closed row is rejected', () => {
        const row = (rejectedOperationIds: string[]) => (
            <table>
                <tbody>
                    <ModelAccessRow
                        user={user}
                        modelId={7}
                        tenantId={2}
                        operations={{}}
                        unresolved={{
                            operation_id: 'uncertain',
                            tenant_id: '2',
                        }}
                        rejectedOperationIds={rejectedOperationIds}
                        onOperation={vi.fn()}
                    />
                </tbody>
            </table>
        )
        const { rerender } = render(row([]))
        expect(screen.getByText('dsh.PROCESSING')).toBeTruthy()
        rerender(row(['uncertain']))
        expect(screen.queryByText('dsh.PROCESSING')).toBeNull()
        expect(screen.getByText('dsh.refresh')).not.toBeDisabled()
        expect(screen.getByText('dsh.save')).toBeDisabled()
    })
    it('refreshes only the completed row using its independent version', async () => {
        const result = { status: 'SUCCEEDED' } as DshOperation
        vi.mocked(getDshModelPolicy).mockResolvedValue({
            user_id: 20,
            version: 4,
            enabled: false,
            monthly_token_limit: 0,
            pending_operation_id: null,
        })
        render(
            <table>
                <tbody>
                    <ModelAccessRow
                        user={{ ...user, pending_operation_id: 'done' }}
                        modelId={7}
                        tenantId={2}
                        operations={{ done: result }}
                        onOperation={vi.fn()}
                    />
                </tbody>
            </table>,
        )
        fireEvent.click(screen.getByText('dsh.refresh'))
        await waitFor(() => expect(screen.getByRole('checkbox')).not.toBeDisabled())
        fireEvent.click(screen.getByRole('checkbox'))
        fireEvent.click(screen.getByText('dsh.save'))
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalled())
        expect(vi.mocked(saveDshPolicy).mock.calls[0][3].expected_version).toBe(4)
    })

    it('uses the model name and a single department tree authorization entry', async () => {
        render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
        await screen.findByRole('heading', { name: 'Root Organization' })
        expect(screen.getByRole('dialog')).toHaveAccessibleName('qwen-max')
        expect(screen.queryByRole('tab')).toBeNull()
        expect(screen.getByRole('textbox', { name: 'dsh.searchDepartmentsAndUsers' })).toBeTruthy()
    })
})
