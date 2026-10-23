import { describe, expect, it } from 'vitest'
import { getPrivateRouter, publicRouter } from '@/routes'

describe('DSH route boundary', () => {
    it('exposes browser consent before and after sign-in without a console permission', () => {
        expect(
            publicRouter.routes.some(
                (route) => route.path === '/desktop-login',
            ),
        ).toBe(true)
        const router = getPrivateRouter([])
        expect(
            router.routes.some((route) => route.path === '/desktop-login'),
        ).toBe(true)
        expect(
            router.routes
                .flatMap((route) => route.children || [])
                .some((route) => route.path === 'sys'),
        ).toBe(false)
        router.dispose()
    })
    it('retains the system route only for system permission', () => {
        const router = getPrivateRouter(['system_config'])
        expect(
            router.routes
                .flatMap((route) => route.children || [])
                .some((route) => route.path === 'sys'),
        ).toBe(true)
        router.dispose()
    })
})
