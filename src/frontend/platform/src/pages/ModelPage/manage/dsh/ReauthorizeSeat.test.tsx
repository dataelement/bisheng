import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { commandDshSeat, getDshSeats } from '@/controllers/API/dsh'
import { resolveOperation } from './useUserPolicyDrafts'
import { ReauthorizeSeat, SeatRestoreContext } from './ReauthorizeSeat'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: ({onOk}: {onOk:(done:()=>void)=>void}) => onOk(()=>{}) }))
vi.mock('@/controllers/API/dsh', async (importOriginal) => ({
    ...await importOriginal<typeof import('@/controllers/API/dsh')>(),
    commandDshSeat: vi.fn(), getDshSeats: vi.fn(),
}))
vi.mock('./useUserPolicyDrafts', () => ({ resolveOperation: vi.fn(), withinSaveDeadline: (promise: Promise<unknown>) => promise }))
const seat = { user_id: '20', tenant_id: '2', state: 'REVOKED', grant_version: 4 }
function mount() {
    const done = vi.fn()
    render(<SeatRestoreContext.Provider value={{tenantId: 2, onRestored: done}}><ReauthorizeSeat userId={20} name="Alice" disabled={false} /></SeatRestoreContext.Provider>)
    return done
}
beforeEach(() => vi.resetAllMocks())
it('restores the exact tenant user with the current grant version and refreshes on success', async () => {
    vi.mocked(getDshSeats).mockResolvedValue({items:[seat], has_more:false, next_cursor:null} as never)
    vi.mocked(commandDshSeat).mockResolvedValue({status:'SUCCEEDED'} as never)
    const done=mount()
    fireEvent.click(screen.getByRole('button'))
    await waitFor(()=>expect(done).toHaveBeenCalledOnce())
    expect(getDshSeats).toHaveBeenCalledWith({tenant_id:'2',user_id:'20',seat_state:'REVOKED',limit:1})
    expect(commandDshSeat).toHaveBeenCalledWith('20','2','reassign',expect.any(String),4)
})
it('rejects a mismatched tenant before sending a command', async () => {
    vi.mocked(getDshSeats).mockResolvedValue({items:[{...seat,tenant_id:'3'}], has_more:false,next_cursor:null} as never)
    mount(); fireEvent.click(screen.getByRole('button'))
    await screen.findByRole('alert')
    expect(commandDshSeat).not.toHaveBeenCalled()
})
it('resolves the original operation after an ambiguous response instead of issuing a second command', async () => {
    vi.mocked(getDshSeats).mockResolvedValue({items:[seat],has_more:false,next_cursor:null} as never)
    vi.mocked(commandDshSeat).mockRejectedValue(new Error('connection lost'))
    vi.mocked(resolveOperation).mockResolvedValue({status:'SUCCEEDED'} as never)
    const done=mount(); fireEvent.click(screen.getByRole('button'))
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button'))
    await waitFor(()=>expect(done).toHaveBeenCalledOnce())
    expect(commandDshSeat).toHaveBeenCalledOnce()
    expect(resolveOperation).toHaveBeenCalledWith(vi.mocked(commandDshSeat).mock.calls[0][3],2)
})

it.each(['command', 'poll', 'recovery', 'http'])(
    'shows capacity guidance from the %s response and permits a fresh authorization after failure',
    async (source) => {
        const failure = { status: 'FAILED', result_code: 'seat_limit_reached' }
        vi.mocked(getDshSeats).mockResolvedValue({ items: [seat], has_more: false, next_cursor: null } as never)
        if (source === 'command') vi.mocked(commandDshSeat).mockResolvedValueOnce(failure as never)
        if (source === 'poll') {
            vi.mocked(commandDshSeat).mockResolvedValueOnce({ status: 'PROCESSING' } as never)
            vi.mocked(resolveOperation).mockResolvedValueOnce(failure as never)
        }
        if (source === 'recovery') {
            vi.mocked(commandDshSeat).mockRejectedValueOnce(new Error('connection lost'))
            vi.mocked(resolveOperation).mockResolvedValueOnce(failure as never)
        }
        if (source === 'http') {
            vi.mocked(commandDshSeat).mockRejectedValueOnce({ response: { status: 403, data: { error: { code: 'seat_limit_reached' } } } })
        }
        const done = mount()
        fireEvent.click(screen.getByRole('button'))
        if (source === 'recovery') {
            await screen.findByText('dsh.reauthorizeFailed')
            fireEvent.click(screen.getByRole('button'))
        }
        expect(await screen.findByRole('alert')).toHaveTextContent('dsh.seatLimitGrantHelp')
        expect(screen.queryByText('dsh.reauthorizeFailed')).toBeNull()
        expect(done).toHaveBeenCalledTimes(0)
        const previousId = vi.mocked(commandDshSeat).mock.calls[0][3]
        vi.mocked(commandDshSeat).mockResolvedValueOnce({ status: 'SUCCEEDED' } as never)
        fireEvent.click(screen.getByRole('button'))
        await waitFor(() => expect(done).toHaveBeenCalledOnce())
        expect(vi.mocked(commandDshSeat).mock.calls[1][3]).not.toBe(previousId)
        expect(screen.queryByRole('alert')).toBeNull()
    },
)
it('keeps other authorization failures distinct from seat capacity', async () => {
    vi.mocked(getDshSeats).mockResolvedValue({ items: [seat], has_more: false, next_cursor: null } as never)
    vi.mocked(commandDshSeat).mockResolvedValue({ status: 'FAILED', result_code: 'license_expired' } as never)
    const done = mount()
    fireEvent.click(screen.getByRole('button'))
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.reauthorizeFailed')
    expect(done).toHaveBeenCalledTimes(0)
})
