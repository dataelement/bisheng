import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SeatsView } from './SeatsView'
import { useState } from 'react'
import {
    getDshSeats,
    commandDshSeat,
} from '@/controllers/API/dsh'
import type { DshOperation, DshOperationRef, DshPage, DshSeat } from '@/types/dsh'
vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@/controllers/API/dsh', async (importOriginal) => ({
    ...await importOriginal<typeof import('@/controllers/API/dsh')>(),
    getDshSeats: vi.fn(),
    commandDshSeat: vi.fn(),
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
afterEach(() => vi.unstubAllGlobals())
describe('DSH seat pagination and commands', () => {
    it('right-aligns filters and shows only available page directions', async () => {
        vi.mocked(getDshSeats).mockImplementation(async (query) => {
            const page = Number(query.cursor || 1)
            return {
                items: [seat(page)],
                next_cursor: page < 3 ? String(page + 1) : null,
                has_more: page < 3,
            }
        })
        const { unmount } = render(
            <SeatsView operations={{}} revision={0} onOperation={vi.fn()} />,
        )
        await screen.findByText('User 1')
        expect(vi.mocked(getDshSeats).mock.calls.at(-1)![0].seat_state).toBeUndefined()
        const search = screen.getByLabelText('dsh.searchUsers')
        const filters = search.parentElement!.parentElement!
        expect(search.parentElement!.classList.contains('w-56')).toBe(true)
        expect(filters.classList.contains('justify-end')).toBe(true)
        expect(filters.classList.contains('items-center')).toBe(true)
        expect(filters.contains(screen.getByLabelText('dsh.seatState'))).toBe(true)
        expect(filters.contains(screen.getByLabelText('dsh.loginState'))).toBe(true)
        expect(screen.queryByRole('button', { name: 'dsh.previous' })).toBeNull()
        const next = screen.getByRole('button', { name: 'dsh.next' })
        expect(next.parentElement!.classList.contains('justify-end')).toBe(true)
        fireEvent.click(next)
        await screen.findByText('User 2')
        expect(screen.getByRole('button', { name: 'dsh.previous' })).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'dsh.next' }))
        await screen.findByText('User 3')
        expect(screen.queryByRole('button', { name: 'dsh.next' })).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'dsh.previous' }))
        await screen.findByText('User 2')
        fireEvent.change(search, { target: { value: 'User' } })
        await screen.findByText('User 1')
        expect(screen.queryByRole('button', { name: 'dsh.previous' })).toBeNull()
        expect(vi.mocked(getDshSeats).mock.calls.at(-1)![0]).toMatchObject({ keyword: 'User' })
        unmount()
    })
    it.each([0, 1])('hides both page directions for a single page with %s seats', async (count) => {
        vi.mocked(getDshSeats).mockResolvedValue({
            items: count ? [seat(1)] : [],
            next_cursor: null,
            has_more: false,
        })
        const { unmount } = render(
            <SeatsView operations={{}} revision={0} onOperation={vi.fn()} />,
        )
        await screen.findByRole('table')
        expect(screen.queryByRole('button', { name: 'dsh.previous' })).toBeNull()
        expect(screen.queryByRole('button', { name: 'dsh.next' })).toBeNull()
        unmount()
    })
    it('renders one page from ten thousand seats without a session entry', async () => {
        const fixtures = Array.from({ length: 10000 }, (_, i) => seat(i + 1))
        vi.mocked(getDshSeats).mockImplementation(async (query) => ({
            items: fixtures.slice(
                query.cursor ? 50 : 0,
                query.cursor ? 100 : 50,
            ),
            next_cursor: query.cursor ? '100' : '50',
            has_more: true,
        }))
        const { unmount } = render(
            <SeatsView operations={{}} revision={0} onOperation={vi.fn()} />,
        )
        await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(51))
        expect(screen.queryByText('dsh.usage')).toBeNull()
        expect(screen.queryByText('dsh.models')).toBeNull()
        expect(screen.queryByLabelText('dsh.department')).toBeNull()
        expect(vi.mocked(getDshSeats).mock.calls[0][0]).not.toHaveProperty('department_id')
        expect(vi.mocked(getDshSeats).mock.calls[0][0].limit).toBe(50)
        expect(screen.queryByRole('button', { name: 'dsh.sessions' })).toBeNull()
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
    it.each(['HTTP', 'HTTPS'])('retries a timed-out mutation over %s with the original ID and version', async (protocol) => {
        if (protocol === 'HTTP') {
            vi.stubGlobal('crypto', {
                getRandomValues: crypto.getRandomValues.bind(crypto),
            })
            expect(crypto.randomUUID).toBeUndefined()
        }
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
        expect(first[3]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
        await act(async () => {
            await onOperation.mock.calls[0][0].retry()
        })
        expect(vi.mocked(commandDshSeat).mock.calls[1]).toEqual(first)
        expect(first).toEqual(['1', '1', 'revoke', expect.any(String), 1])
        unmount()
    })
})

it('shows department and omits a zero count after no sessions', async () => {
    vi.mocked(getDshSeats).mockResolvedValue({ items: [{ ...seat(1), department_name: 'Engineering' }], next_cursor: null, has_more: false })
    const { unmount } = render(<SeatsView operations={{}} revision={0} onOperation={vi.fn()} />)
    await screen.findByText('Engineering')
    expect(screen.getByText('dsh.NO_SESSIONS').closest('td')?.textContent?.trim()).toBe('dsh.NO_SESSIONS')
    expect(screen.queryByRole('columnheader', { name: 'dsh.tenant' })).toBeNull()
    unmount()
})

function SeatCommandHarness() {
    const [operations, setOperations] = useState<Record<string, DshOperation>>({})
    function handleOperation(ref: DshOperationRef, result?: DshOperation) {
        if (result) setOperations((old) => ({ ...old, [ref.operation_id]: result }))
    }
    return <SeatsView operations={operations} revision={0} onOperation={handleOperation} />
}

it.each(['receipt', 'http', 'business'])(
    'shows seat capacity from a %s failure beside the seat and unlocks a fresh retry',
    async (source) => {
        vi.mocked(getDshSeats).mockResolvedValue({ items: [{ ...seat(1), state: 'REVOKED' }], has_more: false, next_cursor: null })
        if (source === 'receipt') {
            vi.mocked(commandDshSeat).mockResolvedValueOnce({ status: 'FAILED', result_code: 'seat_limit_reached' } as DshOperation)
        } else {
            vi.mocked(commandDshSeat).mockRejectedValueOnce({ response: {
                status: source === 'http' ? 403 : 200,
                data: source === 'http' ? { error: { code: 'seat_limit_reached' } } : { status_code: 26112 },
            } })
        }
        const { unmount } = render(<SeatCommandHarness />)
        fireEvent.click(await screen.findByRole('button', { name: 'dsh.reassign' }))
        expect(await screen.findByRole('alert')).toHaveTextContent('dsh.seatLimitGrantHelp')
        expect(screen.getByRole('alert').closest('tr')).toHaveTextContent('dsh.REVOKED')
        expect(screen.getByRole('button', { name: 'dsh.reassign' })).toBeEnabled()
        const previousId = vi.mocked(commandDshSeat).mock.calls[0][3]
        vi.mocked(commandDshSeat).mockResolvedValueOnce({ status: 'SUCCEEDED', result_code: null } as DshOperation)
        fireEvent.click(screen.getByRole('button', { name: 'dsh.reassign' }))
        await waitFor(() => expect(commandDshSeat).toHaveBeenCalledTimes(2))
        expect(vi.mocked(commandDshSeat).mock.calls[1][3]).not.toBe(previousId)
        expect(screen.queryByRole('alert')).toBeNull()
        unmount()
    },
)

it('shows a capacity failure delivered after an operation was accepted', async () => {
    vi.mocked(getDshSeats).mockResolvedValue({ items: [{ ...seat(1), state: 'REVOKED' }], has_more: false, next_cursor: null })
    vi.mocked(commandDshSeat).mockResolvedValue({ status: 'PROCESSING' } as DshOperation)
    const onOperation = vi.fn()
    const { rerender, unmount } = render(<SeatsView operations={{}} revision={0} onOperation={onOperation} />)
    fireEvent.click(await screen.findByRole('button', { name: 'dsh.reassign' }))
    await waitFor(() => expect(onOperation).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('alert')).toBeNull()
    const id = vi.mocked(commandDshSeat).mock.calls[0][3]
    rerender(<SeatsView operations={{ [id]: { status: 'FAILED', result_code: 'seat_limit_reached' } as DshOperation }} revision={0} onOperation={onOperation} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.seatLimitGrantHelp')
    expect(screen.getByRole('button', { name: 'dsh.reassign' })).toBeEnabled()
    unmount()
})
