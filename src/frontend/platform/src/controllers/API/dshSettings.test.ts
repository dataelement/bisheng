import { afterEach, describe, expect, it, vi } from 'vitest'
import request from '@/controllers/request'
import { getDshBrowserConfig, parseDshManagementSettings, saveDshManagementSettings } from './dshSettings'

vi.mock('@/controllers/request', () => ({ default: { get: vi.fn(), put: vi.fn() } }))
afterEach(() => vi.clearAllMocks())

describe('typed DSH management configuration', () => {
    it.each(['javascript:alert(1)', 'http://user:password@host.test/file', '//downloads.test/file'])('rejects unsafe response URLs: %s', (download_url) => {
        expect(() => parseDshManagementSettings({ enabled: true, download_url })).toThrow()
    })
    it('reads the exact browser endpoint and preserves both switch states', async () => {
        vi.mocked(request.get).mockResolvedValue({ management_enabled: true, enabled: false, download_url: null, launch_url: 'dsh-desktop://login' })
        expect(await getDshBrowserConfig()).toEqual({ management_enabled: true, enabled: false, download_url: null, launch_url: 'dsh-desktop://login' })
        expect(request.get).toHaveBeenCalledWith('/api/v1/dsh/browser-config', { signal: undefined })
    })
    it('publishes refresh only after a successful save', async () => {
        const changed = vi.fn()
        window.addEventListener('dsh-settings-changed', changed)
        try {
            const value = { enabled: true, download_url: 'http://downloads.test/file', launch_url: 'dsh-desktop://login' }
            vi.mocked(request.put).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(value)
            await expect(saveDshManagementSettings(value)).rejects.toThrow()
            expect(changed).not.toHaveBeenCalled()
            expect(await saveDshManagementSettings(value)).toEqual(value)
            expect(changed).toHaveBeenCalledTimes(1)
            expect(request.put).toHaveBeenLastCalledWith('/api/v1/dsh/admin/settings', value)
        } finally {
            window.removeEventListener('dsh-settings-changed', changed)
        }
    })
})
