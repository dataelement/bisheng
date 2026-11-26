import request from '@/controllers/request'
import { parseDshLaunchBase } from '@/utils/dshLaunch'
import { notifyDshBrowserConfigChanged } from '@bisheng/api-client'

export type DshManagementSettings = { enabled: boolean; download_url: string | null; launch_url: string; platform_public_url?: string | null }
export type DshBrowserConfig = DshManagementSettings & { management_enabled: boolean }

/** Null/blank keeps the deployment value (BS_DSH_PLATFORM_PUBLIC_URL); otherwise a bare HTTP(S) origin. */
function parsePlatformPublicUrl(raw: unknown): string | null {
    if (raw === null || raw === undefined || raw === '') return null
    if (typeof raw !== 'string') throw new Error('Invalid DSH platform URL')
    const url = new URL(raw)
    if (
        !['http:', 'https:'].includes(url.protocol) || url.username || url.password
        || !['', '/'].includes(url.pathname) || url.search || url.hash
    ) {
        throw new Error('Invalid DSH platform URL')
    }
    return url.origin
}

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
    const platformPublicUrl = parsePlatformPublicUrl('platform_public_url' in raw ? raw.platform_public_url : null)
    return {
        enabled: raw.enabled,
        download_url: raw.download_url,
        launch_url: parseDshLaunchBase('launch_url' in raw ? raw.launch_url : undefined),
        platform_public_url: platformPublicUrl,
    }
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
    notifyDshBrowserConfigChanged()
    return result
}
