import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
    getDshModelUsers,
    getDshOperation,
    getDshModelPolicy,
    saveDshPolicy,
} from '@/controllers/API/dsh'
import type {
    DshModelAccessPage,
    DshModelAccessUser,
    DshOperation,
    DshOperationRef,
} from '@/types/dsh'
import { ModelAccessRow } from './ModelAccessRow'
import { ModelAccessDialog } from './ModelAccessDialog'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@/controllers/API/dsh', () => ({
    getDshModelUsers: vi.fn(),
    getDshOperation: vi.fn(),
    getDshModelPolicy: vi.fn(),
    saveDshPolicy: vi.fn(),
    isDshRequestRejected: (error: Error) => error.message === 'rejected',
}))
const user: DshModelAccessUser = {
    user_id: 20,
    user_name: 'Before first login',
    version: 3,
    enabled: false, monthly_token_limit: 0,
    pending_operation_id: null,
}
const model = { id: 7, name: 'Bailian / qwen-max' }
const page: DshModelAccessPage = {
    model: { ...model, is_root_shared: true },
    tenant_id: 2,
    items: [user],
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
})
afterEach(() => vi.unstubAllGlobals())
describe('model-scoped authorization', () => {
    it.each(['HTTP', 'HTTPS'])('grants a model over %s and retries with the original operation ID', async (protocol) => {
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
        expect(body.operation_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
        expect(body).toEqual({
            operation_id: expect.any(String),
            expected_version: 3,
            enabled: true, monthly_token_limit: 200,
        })
        expect(vi.mocked(saveDshPolicy).mock.calls[0].slice(0, 3)).toEqual([
            '20',
            7,
            '2',
        ])
        expect(screen.getByRole('textbox')).toHaveValue('200')
        fireEvent.click(screen.getByText('dsh.save'))
        expect(saveDshPolicy).toHaveBeenCalledTimes(1)
        const reference = onOperation.mock.calls[0][1] as DshOperationRef
        await act(async () => {
            await reference.retry?.()
        })
        expect(vi.mocked(saveDshPolicy).mock.calls[1][3]).toEqual(body)
    })
    it('revokes only this model using a single-model request', async () => {
        renderRow({
            enabled: true, monthly_token_limit: 100,
        })
        fireEvent.click(screen.getByRole('checkbox'))
        fireEvent.click(screen.getByText('dsh.save'))
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalled())
        expect(vi.mocked(saveDshPolicy).mock.calls[0][3]).toMatchObject({ enabled: false, monthly_token_limit: 0 })
    })
    it('restores an in-progress operation on reopening and blocks a new save', () => {
        const onOperation = renderRow({ pending_operation_id: 'pending-op' })
        expect(onOperation).toHaveBeenCalledWith(20, {
            operation_id: 'pending-op',
            tenant_id: '2', model_id: 7,
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
            <table><tbody><ModelAccessRow
                user={user}
                modelId={7}
                tenantId={2}
                operations={{}}
                unresolved={{ operation_id: 'uncertain', tenant_id: '2' }}
                rejectedOperationIds={rejectedOperationIds}
                onOperation={vi.fn()}
            /></tbody></table>
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
        await waitFor(() =>
            expect(screen.getByRole('checkbox')).not.toBeDisabled(),
        )
        fireEvent.click(screen.getByRole('checkbox'))
        fireEvent.click(screen.getByText('dsh.save'))
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalled())
        expect(vi.mocked(saveDshPolicy).mock.calls[0][3].expected_version).toBe(
            4,
        )
    })
    it('shows an actual provider/model heading and searches users without seat or department filters', async () => {
        const onClose = vi.fn()
        const { rerender } = render(
            <ModelAccessDialog model={model} onClose={onClose} />,
        )
        expect(screen.getByRole('dialog')).toHaveAccessibleName(
            'dsh.modelAccess · Bailian / qwen-max',
        )
        await screen.findByText(user.user_name)
        expect(screen.getByText('dsh.preAuthorizeHelp')).toBeTruthy()
        expect(screen.queryByText('dsh.department')).toBeNull()
        fireEvent.change(
            screen.getByRole('textbox', { name: 'dsh.searchUsers' }),
            { target: { value: 'New' } },
        )
        await waitFor(() =>
            expect(getDshModelUsers).toHaveBeenLastCalledWith(
                7,
                { keyword: 'New', cursor: undefined, limit: 20 },
                expect.any(AbortSignal),
            ),
        )
        await screen.findByText(user.user_name)
        const signal = vi.mocked(getDshModelUsers).mock.calls.at(-1)![2]
        fireEvent.click(
            within(screen.getByRole('dialog')).getByRole('button', {
                name: 'Close',
            }),
        )
        expect(onClose).toHaveBeenCalledOnce()
        rerender(<ModelAccessDialog model={null} onClose={onClose} />)
        expect(signal?.aborted).toBe(true)
        expect(screen.queryByRole('dialog')).toBeNull()
    })
})
