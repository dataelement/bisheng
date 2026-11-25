import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ButtonHTMLAttributes } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { UserProvider } from '@/contexts/userContext'
import { getUserInfo } from '@/controllers/API/user'
import { getOAuth2ConsentDetails, submitOAuth2ConsentDecision } from '@/controllers/API/oauth2'
import { consumeLoginReturnTo, hasOAuthConsentLoginReturnTo, rememberOAuthConsentLoginReturnTo } from '@/utils/loginReturnTo'
import { OAuthConsent } from './index'

vi.mock('@bisheng/ui', () => ({
    Button: ({ variant, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string }) => <button data-variant={variant} {...props} />,
    notification: { open: vi.fn() },
}))
vi.mock('@/components/bs-icons/loading/LoadingState', () => ({ LoadingState: () => <div role="status" /> }))
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }))
vi.mock('@/hooks/useCurrentIdentityRefresh', () => ({ useCurrentIdentityRefresh: vi.fn() }))
vi.mock('@/routes', () => ({
    resolveRoutePermissions: (user: { web_menu?: string[] }) => user.web_menu ?? [],
    resolveAdminLandingPath: () => '/dashboard',
}))
vi.mock('@/controllers/API', () => ({
    delComponentApi: vi.fn(), getComponents: vi.fn(), overridComponent: vi.fn(), saveComponent: vi.fn(),
}))
vi.mock('@/controllers/API/user', () => ({ getUserInfo: vi.fn(), logoutApi: vi.fn() }))
vi.mock('@/controllers/request', () => ({ markSessionKickAck: vi.fn(), requestInterceptor: {} }))
vi.mock('@/controllers/API/oauth2', () => ({ getOAuth2ConsentDetails: vi.fn(), submitOAuth2ConsentDecision: vi.fn() }))

const origin = 'https://bisheng.example'
const assign = vi.fn()
const replace = vi.fn()
const pushState = vi.fn()
const ordinaryUser: Awaited<ReturnType<typeof getUserInfo>> = {
    email: null, phone_number: null, remark: null, delete: 0,
    create_time: '2026-11-25T00:00:00Z', update_time: '2026-11-25T00:00:00Z',
    user_id: 42, user_name: 'Ordinary user', role: 'user',
    web_menu: [], has_admin_console: false, has_workbench: false,
}
const details = {
    request_id: 'fixture-request', client_id: 'fixture-client', client_name: 'Example app',
    scopes: ['openid', 'profile'], redirect_uri: 'https://app.example/callback',
    require_consent: true, expires_in: 300,
}
function visit(path: string) {
    const url = new URL(path, origin)
    vi.stubGlobal('location', { origin, href: url.href, pathname: url.pathname, search: url.search, assign, replace })
}
function renderConsent() {
    return render(<UserProvider><OAuthConsent /></UserProvider>)
}
beforeEach(() => {
    vi.clearAllMocks()
    const values = new Map<string, string>()
    vi.stubGlobal('localStorage', {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
    })
    vi.stubGlobal('history', { pushState })
    vi.stubGlobal('__APP_ENV__', { BASE_URL: '' })
    vi.stubEnv('BASE_URL', '/')
    vi.mocked(getUserInfo).mockResolvedValue(ordinaryUser)
    vi.mocked(getOAuth2ConsentDetails).mockResolvedValue(details)
    vi.mocked(submitOAuth2ConsentDecision).mockResolvedValue({ redirect_uri: details.redirect_uri + '?code=fixture' })
    visit('/oauth-consent?request_id=fixture-request')
})
afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
})

describe('OAuth consent login and ordinary-user entry', () => {
    it.each(['/', '/custom/'])('returns anonymous users through the existing one-shot login consumer at base %s', async (base) => {
        vi.stubEnv('BASE_URL', base)
        const target = origin + base + 'oauth-consent?request_id=fixture-request#consent'
        visit(target)
        vi.mocked(getUserInfo).mockRejectedValueOnce(new Error('not authenticated'))
        renderConsent()
        fireEvent.click(await screen.findByRole('button', { name: 'oauth2.consent.signIn' }))
        expect(assign).toHaveBeenCalledWith(base)
        expect(getOAuth2ConsentDetails).not.toHaveBeenCalled()
        expect(submitOAuth2ConsentDecision).not.toHaveBeenCalled()
        expect(consumeLoginReturnTo()).toBe(target)
        expect(consumeLoginReturnTo()).toBeNull()
    })

    it.each(['/', '/custom/'])('allows an ordinary user to load and approve consent at base %s', async (base) => {
        vi.stubEnv('BASE_URL', base)
        vi.stubGlobal('__APP_ENV__', { BASE_URL: base.slice(0, -1) })
        visit(base + 'oauth-consent?request_id=fixture-request')
        renderConsent()
        fireEvent.click(await screen.findByRole('button', { name: 'oauth2.consent.approve' }))
        await waitFor(() => expect(assign).toHaveBeenCalledWith(details.redirect_uri + '?code=fixture'))
        expect(getOAuth2ConsentDetails).toHaveBeenCalledWith('fixture-request', expect.any(AbortSignal))
        expect(submitOAuth2ConsentDecision).toHaveBeenCalledWith('fixture-request', 'approve')
        expect(replace).not.toHaveBeenCalled()
        expect(pushState).not.toHaveBeenCalled()
    })

    it.each(['/', '/custom/'])('preserves early navigation and lets SSO complete its return at base %s', async (base) => {
        vi.stubEnv('BASE_URL', base)
        vi.stubGlobal('__APP_ENV__', { BASE_URL: base.slice(0, -1) })
        visit(base + 'oauth-consent?request_id=fixture-request')
        const target = location.href
        rememberOAuthConsentLoginReturnTo()
        visit(base)
        render(<UserProvider><div>SSO landing</div></UserProvider>)
        await waitFor(() => expect(localStorage.getItem('UUR_INFO')).toBe('42'))
        expect(replace).not.toHaveBeenCalled()
        expect(pushState).not.toHaveBeenCalled()
        expect(hasOAuthConsentLoginReturnTo()).toBe(true)
        expect(consumeLoginReturnTo()).toBe(target)
        expect(hasOAuthConsentLoginReturnTo()).toBe(false)
    })

    it('lets a base-path SSO root without trailing slash complete its return', async () => {
        vi.stubEnv('BASE_URL', '/custom/')
        vi.stubGlobal('__APP_ENV__', { BASE_URL: '/custom' })
        visit('/custom/oauth-consent?request_id=fixture-request')
        const target = location.href
        rememberOAuthConsentLoginReturnTo()
        visit('/custom')
        render(<UserProvider><div>SSO landing</div></UserProvider>)
        await waitFor(() => expect(localStorage.getItem('UUR_INFO')).toBe('42'))
        expect(pushState).not.toHaveBeenCalled()
        expect(consumeLoginReturnTo()).toBe(target)
    })

    it('keeps workspace-only users out of management even with a pending consent return', async () => {
        vi.mocked(getUserInfo).mockResolvedValue({ ...ordinaryUser, has_workbench: true })
        localStorage.setItem('LOGIN_PATHNAME', origin + '/oauth-consent?request_id=fixture-request')
        localStorage.setItem('LOGIN_PATHNAME_AT', String(Date.now()))
        visit('/admin')
        render(<UserProvider><div>Protected page</div></UserProvider>)
        await waitFor(() => expect(replace).toHaveBeenCalled())
        expect(pushState).not.toHaveBeenCalled()
    })

    it.each(['/admin', '/oauth-consent/admin', '/unrelated/oauth-consent'])('does not exempt protected or lookalike routes: %s', async (path) => {
        localStorage.setItem('LOGIN_PATHNAME', origin + '/oauth-consent?request_id=fixture-request')
        localStorage.setItem('LOGIN_PATHNAME_AT', String(Date.now()))
        visit(path)
        render(<UserProvider><div>Protected page</div></UserProvider>)
        await waitFor(() => expect(pushState).toHaveBeenCalledWith(null, '', '/403'))
    })

    it.each([
        ['https://evil.example/oauth-consent', 0],
        ['//evil.example/oauth-consent', 0],
        ['/oauth-consent', -700000],
        ['/oauth-consent', 700000],
        ['/oauth-consent/admin', 0],
        ['/unrelated/oauth-consent', 0],
    ])('rejects unsafe SSO return %s with time offset %s', async (target, offset) => {
        localStorage.setItem('LOGIN_PATHNAME', String(target))
        localStorage.setItem('LOGIN_PATHNAME_AT', String(Date.now() + Number(offset)))
        visit('/')
        render(<UserProvider><div>Login landing</div></UserProvider>)
        await waitFor(() => expect(pushState).toHaveBeenCalledWith(null, '', '/403'))
    })

    it('keeps invalid request IDs from calling consent APIs', async () => {
        visit('/oauth-consent?request_id=first&request_id=second')
        renderConsent()
        await screen.findByText('oauth2.consent.invalidTitle')
        await waitFor(() => expect(localStorage.getItem('UUR_INFO')).toBe('42'))
        expect(getOAuth2ConsentDetails).not.toHaveBeenCalled()
        expect(submitOAuth2ConsentDecision).not.toHaveBeenCalled()
    })
})
