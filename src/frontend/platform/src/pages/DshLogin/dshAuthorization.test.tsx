import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
    callbackUrl,
    readAuthId,
    useDshAuthorization,
} from './useDshAuthorization'
import { authorizeDsh, denyDsh } from '@/controllers/API/dsh'
vi.mock('@/controllers/API/dsh', () => ({
    authorizeDsh: vi.fn(),
    denyDsh: vi.fn(),
}))
const ticket = {
    identity_ticket: 'fixture-ticket',
    redirect_uri: 'http://127.0.0.1:49152/dsh/callback',
    state: 'fixture-state',
    expires_in: 2,
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.useRealTimers()
})
describe('desktop authorization lifecycle', () => {
    it('accepts a fixed entry and rejects duplicate or malformed identifiers', () => {
        expect(readAuthId('')).toBeNull()
        expect(readAuthId('?auth_id=auth_fixture')).toBe('auth_fixture')
        expect(() => readAuthId('?auth_id=a&auth_id=b')).toThrow()
        expect(() => readAuthId('?auth_id=%3Cscript%3E')).toThrow()
    })
    it('does not issue before consent, suppresses duplicate clicks and clears an expired ticket', async () => {
        vi.useFakeTimers()
        vi.mocked(authorizeDsh).mockResolvedValue(ticket)
        const { result, unmount } = renderHook(() =>
            useDshAuthorization('auth_fixture'),
        )
        expect(authorizeDsh).not.toHaveBeenCalled()
        await act(async () => {
            await Promise.all([
                result.current.handleAuthorize(),
                result.current.handleAuthorize(),
            ])
        })
        expect(authorizeDsh).toHaveBeenCalledTimes(1)
        expect(result.current.authorization?.identity_ticket).toBe(
            'fixture-ticket',
        )
        act(() => {
            vi.advanceTimersByTime(2100)
        })
        expect(result.current.status).toBe('expired')
        expect(result.current.authorization).toBeNull()
        unmount()
        vi.useRealTimers()
    })
    it('denies without issuing a ticket and sends only the whitelisted error', async () => {
        vi.mocked(denyDsh).mockResolvedValue({
            error: 'access_denied',
            redirect_uri: ticket.redirect_uri,
            state: ticket.state,
        })
        const { result } = renderHook(() => useDshAuthorization('auth_fixture'))
        await act(async () => {
            await result.current.handleCancel()
        })
        expect(authorizeDsh).not.toHaveBeenCalled()
        expect(result.current.status).toBe('cancelled')
        const url = new URL(result.current.denialUrl!)
        expect(url.searchParams.get('error')).toBe('access_denied')
        expect(url.searchParams.has('identity_ticket')).toBe(false)
    })
    it('binds callback fields to the current transaction', () => {
        const url = new URL(callbackUrl('auth_fixture', ticket))
        expect([...url.searchParams.keys()]).toEqual([
            'auth_id',
            'identity_ticket',
            'state',
        ])
        expect(url.searchParams.get('auth_id')).toBe('auth_fixture')
    })
    it('aborts a request on unmount without retaining its result', async () => {
        let signal: AbortSignal | undefined
        vi.mocked(authorizeDsh).mockImplementation((_id, value) => {
            signal = value
            return new Promise(() => {})
        })
        const { result, unmount } = renderHook(() =>
            useDshAuthorization('auth_fixture'),
        )
        act(() => {
            void result.current.handleAuthorize()
        })
        unmount()
        expect(signal?.aborted).toBe(true)
    })
})
