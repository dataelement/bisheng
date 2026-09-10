import request from '@/controllers/request'

export type DshManagementSettings = { enabled: boolean; download_url: string | null }
export type DshBrowserConfig = DshManagementSettings & { management_enabled: boolean }

export function parseDshManagementSettings(raw: unknown): DshManagementSettings {
    if (!raw || typeof raw !== 'object' || !('enabled' in raw) || typeof raw.enabled !== 'boolean'
        || !('download_url' in raw) || (raw.download_url !== null && typeof raw.download_url !== 'string')) {
        throw new Error('Invalid DSH settings response')
    }
    if (raw.download_url !== null) {
        const url = new URL(raw.download_url)
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
            throw new Error('Invalid DSH download URL')
        }
    }
    return { enabled: raw.enabled, download_url: raw.download_url }
}

export async function getDshBrowserConfig(signal?: AbortSignal): Promise<DshBrowserConfig> {
    const raw: unknown = await request.get('/api/v1/dsh/browser-config', { signal })
    const settings = parseDshManagementSettings(raw)
    if (!raw || typeof raw !== 'object' || !('management_enabled' in raw) || typeof raw.management_enabled !== 'boolean') {
        throw new Error('Invalid DSH deployment response')
    }
    return { ...settings, management_enabled: raw.management_enabled }
}

export async function saveDshManagementSettings(value: DshManagementSettings): Promise<DshManagementSettings> {
    const result = parseDshManagementSettings(await request.put('/api/v1/dsh/admin/settings', value))
    window.dispatchEvent(new Event('dsh-settings-changed'))
    return result
}
