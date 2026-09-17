import { useEffect, useState } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getDshOperation, saveDshPolicy } from '@/controllers/API/dsh'
import type { DshModelUserPermission, DshOperation } from '@/types/dsh'
import { UserPermissionRow } from './UserPermissionRow'
import { useUserPolicyDrafts, userDraftOf } from './useUserPolicyDrafts'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/API/dsh', () => ({
    getDshOperation: vi.fn(),
    saveDshPolicy: vi.fn(),
    isDshSeatLimitReached: () => false,
    isDshRequestRejected: (error: Error) => error.message === 'rejected',
}))
const item: DshModelUserPermission = {
    user_id: 20,
    user_name: 'alice',
    direct_version: 2,
    direct_enabled: true,
    direct_monthly_token_limit: 500,
    direct_pending_operation_id: null,
    departments: [],
    roles: [],
    sources: [],
    department_match: null,
    authorized: false,
    monthly_token_limit: 0,
}
const onReload = vi.fn()
const visible = [item]
function Harness({ items = visible, modelId = 7 }: { items?: DshModelUserPermission[]; modelId?: number }) {
    const drafts = useUserPolicyDrafts(modelId, onReload)
    const [busy, setBusy] = useState(false)
    const [failure, setFailure] = useState(false)
    const { remember } = drafts
    useEffect(() => remember(items), [items, remember])
    return (
        <>
            <button
                disabled={busy || !drafts.valid || (!drafts.hasChanges && !drafts.hasPending)}
                onClick={async () => {
                    setBusy(true)
                    setFailure(false)
                    try {
                        await drafts.save(2)
                    } catch {
                        setFailure(true)
                    } finally {
                        setBusy(false)
                    }
                }}
            >
                Save
            </button>
            <button onClick={() => drafts.refresh()}>Refresh</button>
            {busy && <span>Saving</span>}
            {failure && <span>Failed</span>}
            <table>
                <tbody>
                    {items.map((user) => {
                        const entry = drafts.entries[user.user_id]
                        return (
                            <UserPermissionRow
                                key={user.user_id}
                                item={entry?.saved ?? user}
                                draft={entry?.draft ?? userDraftOf(user)}
                                disabled={busy}
                                pending={Boolean(entry?.operationId)}
                                onDraftChange={(patch) => drafts.change(user, patch)}
                            />
                        )
                    })}
                </tbody>
            </table>
        </>
    )
}
function renderUser(overrides: Partial<DshModelUserPermission> = {}) {
    return render(<Harness items={[{ ...item, ...overrides }]} />)
}
const input = () => screen.getByRole('textbox')
const save = () => fireEvent.click(screen.getByRole('button', { name: 'Save' }))
beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(saveDshPolicy).mockImplementation(
        async (_id, _model, _tenant, body) =>
            ({
                operation_id: body.operation_id,
                status: 'SUCCEEDED',
            }) as DshOperation,
    )
    onReload.mockImplementation(async (user: DshModelUserPermission) => {
        const draft = vi.mocked(saveDshPolicy).mock.calls.findLast(([id]) => id === String(user.user_id))?.[3]
        return {
            ...user,
            direct_version: user.direct_version + 1,
            direct_enabled: draft?.enabled ?? user.direct_enabled,
            direct_monthly_token_limit: draft?.monthly_token_limit ?? user.direct_monthly_token_limit,
            direct_pending_operation_id: null,
        }
    })
})
afterEach(() => vi.useRealTimers())
describe('staged user authorization', () => {
    it('stages quota edits until explicit Save and retains the final authorization status', async () => {
        renderUser()
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
        fireEvent.change(input(), { target: { value: '900' } })
        fireEvent.blur(input())
        fireEvent.keyDown(input(), { key: 'Enter' })
        expect(screen.queryByRole('switch')).toBeNull()
        expect(saveDshPolicy).not.toHaveBeenCalled()
        expect(screen.getByText('dsh.unauthorized')).toBeVisible()
        save()
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledOnce())
        expect(vi.mocked(saveDshPolicy).mock.calls[0]).toEqual([
            '20',
            7,
            '2',
            {
                operation_id: expect.any(String),
                expected_version: 2,
                enabled: true,
                monthly_token_limit: 900,
            },
        ])
        await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled())
    })
    it('enables personal authorization when saving a positive quota', async () => {
        renderUser({ direct_enabled: false })
        expect(input()).toHaveValue('0')
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
        fireEvent.change(input(), { target: { value: '200000000' } })
        save()
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledOnce())
        expect(vi.mocked(saveDshPolicy).mock.calls[0][3]).toMatchObject({
            enabled: true,
            monthly_token_limit: 200000000,
        })
        await waitFor(() => expect(input()).toBeEnabled())
        expect(input()).toHaveValue('200000000')
        expect(screen.queryByRole('switch')).toBeNull()
    })
    it('closes personal authorization when saving zero quota', async () => {
        renderUser({ direct_enabled: true })
        fireEvent.change(input(), { target: { value: '0' } })
        save()
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledOnce())
        expect(vi.mocked(saveDshPolicy).mock.calls[0][3]).toMatchObject({
            enabled: false,
            monthly_token_limit: 0,
        })
    })
    it('keeps final authorization granted by a department after personal quota becomes zero', async () => {
        renderUser({ authorized: true, monthly_token_limit: 1000000 })
        fireEvent.change(input(), { target: { value: '0' } })
        save()
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledOnce())
        expect(vi.mocked(saveDshPolicy).mock.calls[0][3]).toMatchObject({
            enabled: false,
            monthly_token_limit: 0,
        })
        await waitFor(() => expect(input()).toBeEnabled())
        expect(screen.getByText('dsh.authorized')).toHaveClass('whitespace-nowrap')
    })
    it('saves a cleared quota as zero on explicit save', async () => {
        renderUser({ direct_enabled: true })
        fireEvent.change(input(), { target: { value: '' } })
        fireEvent.blur(input())
        expect(screen.queryByRole('alert')).toBeNull()
        expect(saveDshPolicy).not.toHaveBeenCalled()
        save()
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledOnce())
        expect(vi.mocked(saveDshPolicy).mock.calls[0][3]).toMatchObject({
            enabled: false,
            monthly_token_limit: 0,
        })
        await waitFor(() => expect(input()).toBeEnabled())
        expect(input()).toHaveValue('0')
    })
    it.each(['-1', '1.5', 'abc', '9007199254740992'])('validates personal quota: %s', (value) => {
        renderUser()
        fireEvent.change(input(), { target: { value } })
        expect(screen.getByRole('alert')).toHaveTextContent('dsh.quotaInvalid')
        save()
        expect(saveDshPolicy).not.toHaveBeenCalled()
    })
    it('treats reverted edits and equivalent integer formatting as unchanged', () => {
        renderUser()
        fireEvent.change(input(), { target: { value: '0' } })
        fireEvent.change(input(), { target: { value: '0500' } })
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    })
    it('preserves hidden user drafts across search results and saves them together', async () => {
        const bob = { ...item, user_id: 21, user_name: 'bob' }
        const { rerender } = render(<Harness />)
        fireEvent.change(input(), { target: { value: '800' } })
        rerender(<Harness items={[bob]} />)
        fireEvent.change(input(), { target: { value: '900' } })
        rerender(<Harness items={visible} />)
        expect(input()).toHaveValue('800')
        expect(saveDshPolicy).not.toHaveBeenCalled()
        save()
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledTimes(2))
        expect(
            vi.mocked(saveDshPolicy).mock.calls.map(([id, , , body]) => [id, body.monthly_token_limit]),
        ).toEqual([
            ['20', 800],
            ['21', 900],
        ])
    })
    it('clears drafts when opening another model', () => {
        const { rerender } = render(<Harness />)
        fireEvent.change(input(), { target: { value: '800' } })
        rerender(<Harness modelId={8} />)
        expect(input()).toHaveValue('500')
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    })
    it('preserves failed drafts and refreshes the version before explicit retry', async () => {
        vi.mocked(saveDshPolicy).mockRejectedValueOnce(new Error('rejected'))
        renderUser()
        fireEvent.change(input(), { target: { value: '900' } })
        save()
        await screen.findByText('Failed')
        expect(input()).toHaveValue('900')
        expect(screen.queryByRole('switch')).toBeNull()
        onReload.mockResolvedValueOnce({ ...item, direct_version: 4 })
        fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
        await waitFor(() => expect(onReload).toHaveBeenCalledOnce())
        save()
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledTimes(2))
        expect(vi.mocked(saveDshPolicy).mock.calls[1][3].expected_version).toBe(4)
    })
    it('keeps successful rows committed and the remaining failed row staged', async () => {
        const bob = { ...item, user_id: 21, user_name: 'bob' }
        vi.mocked(saveDshPolicy).mockImplementation(async (id, _m, _t, body) => {
            if (id === '21') throw new Error('rejected')
            return { status: 'SUCCEEDED', operation_id: body.operation_id } as DshOperation
        })
        render(<Harness items={[item, bob]} />)
        const inputs = screen.getAllByRole('textbox')
        fireEvent.change(inputs[0], { target: { value: '800' } })
        fireEvent.change(inputs[1], { target: { value: '900' } })
        save()
        await screen.findByText('Failed')
        save()
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledTimes(3))
        expect(vi.mocked(saveDshPolicy).mock.calls.map(([id]) => id)).toEqual(['20', '21', '21'])
        expect(inputs[1]).toHaveValue('900')
    })
    it('saves later users while the first user is waiting for recovery', async () => {
        const bob = { ...item, user_id: 21, user_name: 'bob' }
        let finish: (value: DshOperation) => void = () => {}
        vi.mocked(saveDshPolicy).mockImplementation((id) =>
            id === '20'
                ? new Promise((resolve) => {
                      finish = resolve
                  })
                : Promise.resolve({ status: 'SUCCEEDED' } as DshOperation),
        )
        render(<Harness items={[item, bob]} />)
        const inputs = screen.getAllByRole('textbox')
        fireEvent.change(inputs[0], { target: { value: '800' } })
        fireEvent.change(inputs[1], { target: { value: '900' } })
        save()
        await waitFor(() => expect(onReload).toHaveBeenCalledWith(bob))
        expect(saveDshPolicy).toHaveBeenCalledTimes(2)
        expect(screen.getByText('Saving')).toBeTruthy()
        await act(async () => finish({ status: 'SUCCEEDED' } as DshOperation))
        await waitFor(() => expect(screen.queryByText('Saving')).toBeNull())
    })
    it.each(['processing', 'lookup stalled', 'save stalled', 'reload stalled'])(
        'bounds waiting and checks the original operation on next Save: %s',
        async (scenario) => {
            vi.useFakeTimers()
            const stalled = new Promise<DshOperation>(() => {})
            vi.mocked(getDshOperation).mockImplementation(
                async (id) =>
                    ({
                        operation_id: id,
                        status: 'PROCESSING',
                    }) as DshOperation,
            )
            if (scenario === 'lookup stalled') vi.mocked(getDshOperation).mockReturnValue(stalled)
            vi.mocked(saveDshPolicy).mockImplementation(
                async (_u, _m, _t, body) =>
                    ({
                        status: scenario === 'reload stalled' ? 'SUCCEEDED' : 'PROCESSING',
                        operation_id: body.operation_id,
                    }) as DshOperation,
            )
            if (scenario === 'save stalled') vi.mocked(saveDshPolicy).mockReturnValue(stalled)
            if (scenario === 'reload stalled') onReload.mockReturnValueOnce(new Promise(() => {}))
            renderUser()
            fireEvent.change(input(), { target: { value: '900' } })
            await act(async () => {
                save()
                await vi.advanceTimersByTimeAsync(10001)
            })
            expect(screen.queryByText('Saving')).toBeNull()
            expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
            expect(input()).toBeDisabled()
            const originalId = vi.mocked(saveDshPolicy).mock.calls[0][3].operation_id
            vi.mocked(getDshOperation).mockResolvedValue({
                status: 'SUCCEEDED',
                operation_id: originalId,
            } as DshOperation)
            await act(async () => save())
            expect(getDshOperation).toHaveBeenLastCalledWith(originalId, '2', expect.any(AbortSignal))
            expect(saveDshPolicy).toHaveBeenCalledOnce()
            expect(input()).toBeEnabled()
            expect(input()).toHaveValue('900')
        },
    )
    it('waits for authoritative reload when the saved revision is still stale', async () => {
        onReload.mockResolvedValueOnce(item)
        renderUser()
        fireEvent.change(input(), { target: { value: '900' } })
        save()
        await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled())
        expect(input()).toBeDisabled()
        expect(input()).toHaveValue('900')
        const operationId = vi.mocked(saveDshPolicy).mock.calls[0][3].operation_id
        vi.mocked(getDshOperation).mockResolvedValue({
            status: 'SUCCEEDED',
            operation_id: operationId,
        } as DshOperation)
        save()
        await waitFor(() => expect(input()).toBeEnabled())
        expect(saveDshPolicy).toHaveBeenCalledOnce()
    })
    it('reads an existing pending operation on Save without creating a mutation', async () => {
        renderUser({ direct_pending_operation_id: 'old-op' })
        expect(getDshOperation).not.toHaveBeenCalled()
        expect(input()).toBeDisabled()
        vi.mocked(getDshOperation).mockResolvedValue({
            status: 'SUCCEEDED',
            operation_id: 'old-op',
        } as DshOperation)
        save()
        await waitFor(() => expect(input()).toBeEnabled())
        expect(saveDshPolicy).not.toHaveBeenCalled()
    })
    it('guards duplicate clicks and releases controls after confirmed failure', async () => {
        let complete: (operation: DshOperation) => void = () => {}
        vi.mocked(saveDshPolicy).mockReturnValue(
            new Promise((resolve) => {
                complete = resolve
            }),
        )
        renderUser()
        fireEvent.change(input(), { target: { value: '900' } })
        save()
        save()
        expect(saveDshPolicy).toHaveBeenCalledOnce()
        await act(async () => complete({ status: 'FAILED' } as DshOperation))
        expect(input()).toBeEnabled()
        expect(input()).toHaveValue('900')
    })
})
