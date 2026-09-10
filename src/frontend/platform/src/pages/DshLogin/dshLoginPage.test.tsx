import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createContext } from 'react'
import english from '../../../public/locales/en-US/bs.json'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DshLogin } from './index'
import { consumeLoginReturnTo } from '@/utils/loginReturnTo'

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
const origin = 'http://192.168.106.109:13001'
const assign = vi.fn()
beforeEach(() => {
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
        { leaf_tenant_name: 'Default Tenant', tenant_name: null, expected: 'dshadmin (Default Tenant)' },
        { leaf_tenant_name: 'Current Tenant', tenant_name: 'Old Tenant', expected: 'dshadmin (Current Tenant)' },
        { tenant_name: 'Legacy Tenant', expected: 'dshadmin (Legacy Tenant)' },
        { leaf_tenant_name: '  ', tenant_name: null, expected: 'dshadmin.' },
        { expected: 'dshadmin.' },
    ])('shows the available tenant without empty parentheses: $expected', async ({ expected, ...tenant }) => {
        identity.user = { user_id: 1, user_name: 'dshadmin', ...tenant }
        vi.stubGlobal('location', { origin, pathname: '/desktop-login', href: origin + '/desktop-login?auth_id=fixture', search: '?auth_id=fixture', assign })
        render(<DshLogin />)
        await screen.findByRole('button', { name: english.dsh.authorize })
        expect(screen.getByText(/Authorize DSH Desktop as/).textContent).toContain(expected)
        expect(screen.getByText(/Authorize DSH Desktop as/).textContent).not.toContain('()')
    })
})
