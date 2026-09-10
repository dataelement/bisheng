import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createContext } from 'react'
import english from '../../../public/locales/en-US/bs.json'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DshLogin } from './index'
import { consumeLoginReturnTo } from '@/utils/loginReturnTo'
import { getDshBrowserConfig } from '@/controllers/API/dshSettings'
import request from '@/controllers/request'
vi.mock('@/controllers/request', () => ({ default: { get: vi.fn() } }))

const identity = vi.hoisted(() => ({ user: null as null | {
    user_id: number; user_name: string; tenant_name?: string | null; leaf_tenant_name?: string | null;
} }))
vi.mock('@/contexts/userContext', () => ({ userContext: createContext(identity) }))
vi.mock('react-i18next', async () => {
    const { createInstance } = await import('i18next')
    const { default: messages } = await import('../../../public/locales/en-US/bs.json')
    const i18n = createInstance()
    await i18n.init({ lng: 'en', resources: { en: { translation: messages } } })
    return { useTranslation: () => ({ t: i18n.t.bind(i18n) }) }
})
vi.mock('@/controllers/API/dsh', () => ({
    getDshConfig: vi.fn().mockResolvedValue({ enabled: true, client_id: 'dsh-desktop', contract_version: '0.4.0' }),
    authorizeDsh: vi.fn(),
    denyDsh: vi.fn(),
}))
vi.mock('@/controllers/API/dshSettings', () => ({ getDshBrowserConfig: vi.fn() }))
const origin = 'http://192.168.106.109:13001'
const assign = vi.fn()
beforeEach(() => {
    vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: null, launch_url: 'dsh-desktop://login' })
    vi.mocked(request.get).mockResolvedValue({ department_name: null })
    assign.mockClear()
    identity.user = null
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
    it('uses the saved HTTP download address without a frontend build variable', async () => {
        vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: 'http://downloads.test/dsh', launch_url: 'dsh-desktop://login' })
        vi.stubGlobal('location', { origin, pathname: '/desktop-login', search: '', assign })
        render(<DshLogin />)
        expect(await screen.findByRole('link', { name: english.dsh.download })).toHaveAttribute('href', 'http://downloads.test/dsh')
    })
    it('removes download and launch actions when the business switch closes', async () => {
        vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: false, download_url: 'http://downloads.test/dsh', launch_url: 'dsh-desktop://login' })
        vi.stubGlobal('location', { origin, pathname: '/desktop-login', search: '', assign })
        render(<DshLogin />)
        await screen.findByText(english.dsh.disabled)
        expect(screen.queryByRole('button', { name: english.dsh.openDesktop })).toBeNull()
        expect(screen.queryByRole('link', { name: english.dsh.download })).toBeNull()
    })
    it('returns to the complete authorization URL after the explicit login action', async () => {
        const search = '?auth_id=fixture-authorization'
        vi.stubGlobal('location', { origin, pathname: '/desktop-login', href: origin + '/desktop-login' + search, search, assign })
        render(<DshLogin />)
        fireEvent.click(await screen.findByRole('button', { name: english.dsh.login }))
        expect(assign).toHaveBeenCalledWith('/')
        expect(consumeLoginReturnTo()).toBe(origin + '/desktop-login' + search)
    })
    it('allows launching Desktop with the HTTP platform address', async () => {
        vi.stubGlobal('location', { origin, pathname: '/desktop-login', href: origin + '/desktop-login', search: '', assign })
        render(<DshLogin />)
        const launch = await screen.findByRole('button', { name: english.dsh.openDesktop })
        expect(launch).toBeEnabled()
        fireEvent.click(launch)
        const link = new URL(assign.mock.calls[0][0])
        expect(link.protocol).toBe('dsh-desktop:')
        expect(link.searchParams.get('server')).toBe(origin)
    })
})


describe('desktop consent identity', () => {
    it.each([
        { department: 'Engineering', expected: 'dshadmin (Engineering)' },
        { department: null, expected: 'dshadmin.' },
        { department: '  ', expected: 'dshadmin.' },
    ])('shows the primary department without tenant or empty parentheses: $expected', async ({ expected, department }) => {
        vi.mocked(request.get).mockResolvedValue({ department_name: department })
        identity.user = { user_id: 1, user_name: 'dshadmin', tenant_name: 'Hidden Tenant' }
        vi.stubGlobal('location', { origin, pathname: '/desktop-login', href: origin + '/desktop-login?auth_id=fixture', search: '?auth_id=fixture', assign })
        render(<DshLogin />)
        await screen.findByRole('button', { name: english.dsh.authorize })
        await waitFor(() => expect(screen.getByText(/Authorize DSH Desktop as/).textContent).toContain(expected))
        expect(screen.queryByText(/Hidden Tenant/)).toBeNull()
        expect(screen.getByText(/Authorize DSH Desktop as/).textContent).not.toContain('()')
    })
})
