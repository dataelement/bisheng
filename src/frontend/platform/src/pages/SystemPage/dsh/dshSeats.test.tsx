import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SeatsView } from './SeatsView'
import {
    getDshSeats,
    getDshSessions,
    commandDshSeat,
} from '@/controllers/API/dsh'
import type { DshPage, DshSeat } from '@/types/dsh'
vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@/controllers/API/dsh', () => ({
    getDshSeats: vi.fn(),
    getDshSessions: vi.fn(),
    commandDshSeat: vi.fn(),
    isDshRequestRejected: () => false,
}))
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({
    bsConfirm: ({ onOk }: { onOk: (next: () => void) => void }) =>
        onOk(() => {}),
}))
function seat(id: number): DshSeat {
    return {
        seat_id: `seat${id}`,
        tenant_id: '1',
        user_id: String(id),
        state: 'ASSIGNED',
        grant_version: 1,
        username: `user${id}`,
        display_name: `User ${id}`,
        profile_version: 1,
        profile_synced_at: null,
        last_login_at: null,
        last_seen_at: null,
        active_session_count: 0,
        login_state: 'NO_SESSIONS',
        created_at: '2026-09-09T00:00:00Z',
    }
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.useRealTimers()
})
describe('DSH seat pagination and commands', () => {
    it('renders one page from ten thousand seats and loads sessions independently', async () => {
        const fixtures = Array.from({ length: 10000 }, (_, i) => seat(i + 1))
        vi.mocked(getDshSeats).mockImplementation(async (query) => ({
            items: fixtures.slice(
                query.cursor ? 50 : 0,
                query.cursor ? 100 : 50,
            ),
            next_cursor: query.cursor ? '100' : '50',
            has_more: true,
        }))
        vi.mocked(getDshSessions).mockResolvedValue({
            items: [],
            next_cursor: null,
            has_more: false,
        })
        const { unmount } = render(
            <SeatsView operations={{}} revision={0} onOperation={vi.fn()} />,
        )
        await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(51))
        expect(screen.queryByText('dsh.usage')).toBeNull()
        expect(screen.queryByText('dsh.models')).toBeNull()
        expect(screen.queryByLabelText('dsh.department')).toBeNull()
        expect(vi.mocked(getDshSeats).mock.calls[0][0]).not.toHaveProperty('department_id')
        expect(vi.mocked(getDshSeats).mock.calls[0][0].limit).toBe(50)
        fireEvent.click(screen.getAllByText('dsh.sessions')[0])
        await waitFor(() =>
            expect(getDshSessions).toHaveBeenCalledWith(
                '1',
                '1',
                undefined,
                expect.any(AbortSignal),
            ),
        )
        expect(screen.getByRole('dialog')).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Close' }))
        expect(screen.queryByRole('dialog')).toBeNull()
        fireEvent.click(screen.getAllByText('dsh.next')[0])
        await waitFor(() => expect(screen.getByText('User 51')).toBeTruthy())
        expect(screen.queryByText('User 1')).toBeNull()
        expect(vi.mocked(getDshSeats).mock.calls.at(-1)![0].cursor).toBe('50')
        unmount()
    })
    it('aborts stale filter responses and resets the cursor', async () => {
        let resolveOld: ((value: DshPage<DshSeat>) => void) | undefined
        vi.mocked(getDshSeats).mockImplementation((query) =>
            query.keyword === 'new'
                ? Promise.resolve({
                      items: [seat(2)],
                      next_cursor: null,
                      has_more: false,
                  })
                : new Promise((resolve) => {
                      resolveOld = resolve
                  }),
        )
        const { unmount } = render(
            <SeatsView operations={{}} revision={0} onOperation={vi.fn()} />,
        )
        await waitFor(() => expect(getDshSeats).toHaveBeenCalled())
        const oldSignal = vi.mocked(getDshSeats).mock.calls[0][1]
        fireEvent.change(screen.getByLabelText('dsh.searchUsers'), {
            target: { value: 'new' },
        })
        await waitFor(() => expect(screen.getByText('User 2')).toBeTruthy())
        await act(async () => {
            resolveOld?.({
                items: [seat(1)],
                next_cursor: 'stale',
                has_more: true,
            })
        })
        expect(oldSignal?.aborted).toBe(true)
        expect(screen.queryByText('User 1')).toBeNull()
        expect(
            vi.mocked(getDshSeats).mock.calls.at(-1)![0].cursor,
        ).toBeUndefined()
        unmount()
    })
    it('retries a timed-out mutation with the exact original ID and version', async () => {
        vi.mocked(getDshSeats).mockResolvedValue({
            items: [seat(1)],
            next_cursor: null,
            has_more: false,
        })
        vi.mocked(commandDshSeat).mockRejectedValue(new Error('Timeout'))
        const onOperation = vi.fn()
        const { unmount } = render(
            <SeatsView
                operations={{}}
                revision={0}
                onOperation={onOperation}
            />,
        )
        await waitFor(() => expect(screen.getByText('dsh.revoke')).toBeTruthy())
        fireEvent.click(screen.getByText('dsh.revoke'))
        await waitFor(() => expect(commandDshSeat).toHaveBeenCalledTimes(1))
        const first = vi.mocked(commandDshSeat).mock.calls[0]
        await act(async () => {
            await onOperation.mock.calls[0][0].retry()
        })
        expect(vi.mocked(commandDshSeat).mock.calls[1]).toEqual(first)
        expect(first).toEqual(['1', '1', 'revoke', expect.any(String), 1])
        unmount()
    })
})
