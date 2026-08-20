import { resolvePlatformEntry } from '@/contexts/userContext'
import { describe, expect, it } from 'vitest'

describe('resolvePlatformEntry', () => {
    it('keeps users with admin-console access in the platform', () => {
        expect(resolvePlatformEntry({ has_admin_console: true, has_workbench: true }, [])).toBe('platform')
    })

    it('redirects workbench-only users without showing an admin permission error', () => {
        expect(resolvePlatformEntry({ has_admin_console: false, has_workbench: true }, [])).toBe('workspace')
    })

    it('forbids users who have neither platform nor workspace access', () => {
        expect(resolvePlatformEntry({ has_admin_console: false, has_workbench: false }, [])).toBe('forbidden')
    })

    it('supports legacy menu permissions when explicit access flags are absent', () => {
        expect(resolvePlatformEntry({ role: 'user' }, ['workstation'])).toBe('workspace')
        expect(resolvePlatformEntry({ role: 'user' }, [])).toBe('forbidden')
    })
})
