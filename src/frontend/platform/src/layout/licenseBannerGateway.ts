const ONE_DAY_MS = 24 * 60 * 60 * 1000

type GatewayCheckedAt = {
    license_code: string
    checked_at?: string | null
}

/**
 * Whether Banner should call Gateway `GET /api/license/status`.
 *
 * Fresh `gateway.checked_at` (within 24 hours) skips the Gateway round-trip.
 * Missing row, missing/invalid timestamp, or age over one day triggers a fetch.
 */
export function shouldFetchGatewayLicenseStatus(
    licenses: GatewayCheckedAt[] | null | undefined,
    nowMs: number = Date.now(),
    isPro?: boolean,
): boolean {
    // Open-source / no Java Gateway: `/api/license/status` is not mounted and
    // would 404 in the browser Network panel. Commercial (`pro`) still probes.
    if (isPro !== true) {
        return false
    }
    const gateway = licenses?.find((item) => item.license_code === "gateway")
    if (!gateway?.checked_at) {
        return true
    }
    const checkedAtMs = Date.parse(gateway.checked_at)
    if (Number.isNaN(checkedAtMs)) {
        return true
    }
    return nowMs - checkedAtMs > ONE_DAY_MS
}
