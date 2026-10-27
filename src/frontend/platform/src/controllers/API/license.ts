import axios from "@/controllers/request"

export type LicenseSeverity = 'normal' | 'warning' | 'critical' | 'expired' | 'unknown'

export type CommercialDisplayState = 'normal' | 'expiring' | 'expired' | 'unknown'

// Mirrors the gateway LicenseStatusHolder.LicenseStatus record (snake_case via the gateway's
// global SnakeCaseStrategy ObjectMapper). Feature 037 / F070 report body.
export interface LicenseStatus {
    version: string | null
    expire_day: string | null
    days_remaining: number | null
    severity: LicenseSeverity
    expired: boolean
    checked_at: string | null
}

export interface CommercialLicenseItem {
    license_code: string
    license_name: string
    display_state: CommercialDisplayState
    expire_date: string | null
    days_remaining: number | null
    checked_at: string | null
}

export interface CommercialLicenseStatus {
    licenses: CommercialLicenseItem[]
    checked_at: string | null
}

/**
 * Fetch the current license status from the gateway (gateway-self-handled `/api/license/status`).
 *
 * Returns null when the status is unavailable — e.g. open-source deployments have no gateway, so
 * the request 404s. `silent: true` suppresses the global error toast / redirect; any failure simply
 * yields null and the Banner stays hidden. See feature 037 design §5 (坑 5).
 */
export async function getLicenseStatus(): Promise<LicenseStatus | null> {
    try {
        return await axios.get(`/api/license/status`, { silent: true } as any)
    } catch {
        return null
    }
}

export async function reportGatewayLicense(data: LicenseStatus): Promise<void> {
    try {
        await axios.post(`/api/v1/commercial-licenses/gateway`, data, { silent: true } as any)
    } catch {
        // Best-effort write; aggregation still reads the last successful row.
    }
}

export async function getCommercialLicenseStatus(): Promise<CommercialLicenseStatus | null> {
    try {
        return await axios.get(`/api/v1/commercial-licenses/status`, { silent: true } as any)
    } catch {
        return null
    }
}
