import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createContext } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DshLogin } from './index'
import { consumeLoginReturnTo } from '@/utils/loginReturnTo'

vi.mock('@/contexts/userContext', () => ({
    userContext: createContext({ user: null }),
}))
vi.mock('@/controllers/API/dsh', () => ({
    getDshConfig: vi.fn().mockResolvedValue({ enabled: true, client_id: 'dsh-desktop', contract_version: '0.4.0' }),
    authorizeDsh: vi.fn(),
    denyDsh: vi.fn(),
}))
const origin = 'http://192.168.106.109:13001'
const assign = vi.fn()
beforeEach(() => {
    assign.mockClear()
    const values = new Map<string, string>()
    vi.stubGlobal('localStorage', {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
    })
})
afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
})
describe('desktop HTTP login entry', () => {
    it('returns to the complete authorization URL after the explicit login action', async () => {
        const search = '?auth_id=fixture-authorization'
        vi.stubGlobal('location', { origin, pathname: '/desktop-login', href: origin + '/desktop-login' + search, search, assign })
        render(<DshLogin />)
        fireEvent.click(await screen.findByRole('button', { name: 'dsh.login' }))
        expect(assign).toHaveBeenCalledWith('/')
        expect(consumeLoginReturnTo()).toBe(origin + '/desktop-login' + search)
    })
    it('allows launching Desktop with the HTTP platform address', async () => {
        vi.stubGlobal('location', { origin, pathname: '/desktop-login', href: origin + '/desktop-login', search: '', assign })
        render(<DshLogin />)
        const launch = await screen.findByRole('button', { name: 'dsh.openDesktop' })
        expect(launch).toBeEnabled()
        fireEvent.click(launch)
        const link = new URL(assign.mock.calls[0][0])
        expect(link.protocol).toBe('dsh-desktop:')
        expect(link.searchParams.get('server')).toBe(origin)
    })
})
