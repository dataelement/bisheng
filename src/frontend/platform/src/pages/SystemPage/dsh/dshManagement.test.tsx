import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { OperationStatus } from './OperationStatus'
import { PolicyEditor } from './PolicyEditor'
import { getDshOperation, saveDshPolicy } from '@/controllers/API/dsh'
import type { DshOperation, DshPolicy } from '@/types/dsh'
vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@/controllers/API/dsh', () => ({
    getDshOperation: vi.fn(),
    saveDshPolicy: vi.fn(),
    isDshRequestRejected: () => false,
}))
const ref = { operation_id: 'fixture-op', tenant_id: '1' }
const operation: DshOperation = {
    operation_id: ref.operation_id,
    tenant_id: 1,
    user_id: 2,
    actor_user_id: 3,
    action: 'UPDATE_POLICY',
    status: 'PROCESSING',
    before_values: { version: 1 },
    after_values: { version: 2 },
    expected_grant_version: null,
    expected_policy_version: 1,
    committed_at: null,
    effective_at: null,
    result_code: null,
    result_payload: { phase: 'SQL_COMMITTED' },
}
const policy: DshPolicy = {
    tenant_id: 1,
    available_models: [],
    available_models_source: 'live',
    last_call: null,
    last_call_source: 'persisted',
    version: 1,
    models: [],
    quota_sync_state: 'READY',
    usage: null,
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.useRealTimers()
})
describe('DSH admin uncertainty and audit', () => {
    it('renders processing audit without success and aborts polling on exit', async () => {
        vi.mocked(getDshOperation).mockResolvedValue(operation)
        const onUpdate = vi.fn()
        const { unmount } = render(
            <OperationStatus
                reference={ref}
                operation={operation}
                onUpdate={onUpdate}
            />,
        )
        await waitFor(() =>
            expect(onUpdate).toHaveBeenCalledWith(ref, operation),
        )
        expect(screen.getByRole('status').textContent).toContain(
            'dsh.PROCESSING',
        )
        expect(screen.queryByText('dsh.SUCCEEDED')).toBeNull()
        expect(screen.getByText(/"version": 1/)).toBeTruthy()
        expect(screen.getByText(/SQL_COMMITTED/)).toBeTruthy()
        const signal = vi.mocked(getDshOperation).mock.calls[0][2]
        unmount()
        expect(signal?.aborted).toBe(true)
    })
    it('bounds failed polling and retains the operation ID', async () => {
        vi.useFakeTimers()
        vi.mocked(getDshOperation).mockRejectedValue(new Error('Unavailable'))
        const { unmount } = render(
            <OperationStatus reference={ref} onUpdate={vi.fn()} />,
        )
        await act(async () => {
            await vi.advanceTimersByTimeAsync(250000)
        })
        expect(getDshOperation).toHaveBeenCalledTimes(30)
        expect(screen.getByText('dsh.pollPaused')).toBeTruthy()
        expect(screen.getByText('fixture-op')).toBeTruthy()
        expect(screen.queryByText('dsh.SUCCEEDED')).toBeNull()
        unmount()
        vi.useRealTimers()
    })
    it('retains independent inputs on timeout and prevents a second operation', async () => {
        vi.mocked(saveDshPolicy).mockRejectedValue(new Error('Timeout'))
        const onOperation = vi.fn()
        render(
            <PolicyEditor
                userId="2"
                tenantId="1"
                policy={{
                    ...policy,
                    available_models: [
                        { id: 7, name: 'Model', is_root_shared: false },
                    ],
                    models: [{ model_id: 7, monthly_token_limit: 0 }],
                }}
                operations={{}}
                onOperation={onOperation}
                onReload={vi.fn()}
            />,
        )
        expect(screen.getByText('dsh.zeroModelQuota')).toBeTruthy()
        fireEvent.change(screen.getByRole('textbox'), {
            target: { value: '1000' },
        })
        fireEvent.click(screen.getByText('dsh.save'))
        await waitFor(() =>
            expect(screen.getByRole('alert').textContent).toContain(
                'dsh.saveUncertain',
            ),
        )
        expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe(
            '1000',
        )
        fireEvent.click(screen.getByText('dsh.save'))
        expect(saveDshPolicy).toHaveBeenCalledTimes(1)
        expect(vi.mocked(saveDshPolicy).mock.calls[0][2]).toMatchObject({
            expected_version: 1,
            models: [{ model_id: 7, monthly_token_limit: 1000 }],
        })
        expect(onOperation.mock.calls[0][0].operation_id).toBeTruthy()
    })
    it('saves different limits per model and removes an unavailable configured model', async () => {
        vi.mocked(saveDshPolicy).mockResolvedValue(operation)
        render(
            <PolicyEditor
                userId="2"
                tenantId="1"
                policy={{
                    ...policy,
                    available_models: [
                        { id: 7, name: 'First', is_root_shared: false },
                        { id: 8, name: 'Second', is_root_shared: false },
                    ],
                    models: [
                        { model_id: 7, monthly_token_limit: 100 },
                        { model_id: 99, monthly_token_limit: 300 },
                    ],
                }}
                operations={{}}
                onOperation={vi.fn()}
                onReload={vi.fn()}
            />,
        )
        fireEvent.click(screen.getByRole('checkbox', { name: 'Second' }))
        const inputs = screen.getAllByRole('textbox')
        fireEvent.change(inputs[0], { target: { value: '1000' } })
        fireEvent.change(inputs[1], { target: { value: '200' } })
        fireEvent.click(
            screen.getByRole('checkbox', { name: 'dsh.unavailableModel' }),
        )
        fireEvent.click(screen.getByText('dsh.save'))
        await waitFor(() => expect(saveDshPolicy).toHaveBeenCalledTimes(1))
        const body = vi.mocked(saveDshPolicy).mock.calls[0][2]
        expect(body.models).toEqual([
            { model_id: 7, monthly_token_limit: 1000 },
            { model_id: 8, monthly_token_limit: 200 },
        ])
        expect(body).not.toHaveProperty('monthly_token_limit')
    })
    it.each(['', '-1', '1.5', '9007199254740992'])(
        'rejects invalid model quota %s without sending an operation',
        (limit) => {
            render(
                <PolicyEditor
                    userId="2"
                    tenantId="1"
                    policy={{
                        ...policy,
                        available_models: [
                            { id: 7, name: 'First', is_root_shared: false },
                        ],
                        models: [{ model_id: 7, monthly_token_limit: 100 }],
                    }}
                    operations={{}}
                    onOperation={vi.fn()}
                    onReload={vi.fn()}
                />,
            )
            fireEvent.change(screen.getByRole('textbox'), {
                target: { value: limit },
            })
            fireEvent.click(screen.getByText('dsh.save'))
            expect(saveDshPolicy).not.toHaveBeenCalled()
        },
    )
    it('preserves the operation ID and model configuration when retrying an uncertain save', async () => {
        vi.mocked(saveDshPolicy).mockRejectedValue(new Error('Timeout'))
        const onOperation = vi.fn()
        render(
            <PolicyEditor
                userId="2"
                tenantId="1"
                policy={policy}
                operations={{}}
                onOperation={onOperation}
                onReload={vi.fn()}
            />,
        )
        expect(screen.getByText('dsh.blockedPolicy')).toBeTruthy()
        expect(screen.queryByText('dsh.zeroModelQuota')).toBeNull()
        fireEvent.click(screen.getByText('dsh.save'))
        await screen.findByRole('alert')
        const firstBody = vi.mocked(saveDshPolicy).mock.calls[0][2]
        await act(async () => {
            await onOperation.mock.calls[0][0].retry()
        })
        expect(vi.mocked(saveDshPolicy).mock.calls[1][2]).toEqual(firstBody)
        expect(firstBody.models).toEqual([])
    })
    it('restores the pending operation and prevents another save after reopening', () => {
        const onOperation = vi.fn()
        render(
            <PolicyEditor
                userId="2"
                tenantId="1"
                policy={{
                    ...policy,
                    pending_operation_id: 'original-operation',
                }}
                operations={{}}
                onOperation={onOperation}
                onReload={vi.fn()}
            />,
        )
        expect(onOperation).toHaveBeenCalledWith({
            operation_id: 'original-operation',
            tenant_id: '1',
        })
        fireEvent.click(screen.getByText('dsh.save'))
        expect(saveDshPolicy).not.toHaveBeenCalled()
    })
})
