import { act, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { OperationStatus } from './OperationStatus'
import { getDshOperation } from '@/controllers/API/dsh'
import type { DshOperation } from '@/types/dsh'
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
})
