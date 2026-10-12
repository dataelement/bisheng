import type { DshLicense } from '@/types/dsh'

export function licenseStatusKey(license: DshLicense): string {
    const status = license.status.toLowerCase()
    if (status === 'active' && license.source === 'builtin') return 'free'
    if (status === 'active' && license.source === 'signed') return 'commercial'
    return status
}
