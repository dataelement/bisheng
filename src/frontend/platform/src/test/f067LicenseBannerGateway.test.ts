import { describe, expect, it } from "vitest"

import { shouldFetchGatewayLicenseStatus } from "@/layout/licenseBannerGateway"

const NOW = Date.parse("2026-09-14T14:00:00+08:00")
const HOUR = 60 * 60 * 1000

function gatewayAt(checkedAt: string | null) {
    return [{ license_code: "gateway", checked_at: checkedAt }]
}

describe("shouldFetchGatewayLicenseStatus", () => {
    it("fetches when there is no gateway row", () => {
        expect(shouldFetchGatewayLicenseStatus([], NOW)).toBe(true)
        expect(shouldFetchGatewayLicenseStatus(undefined, NOW)).toBe(true)
        expect(
            shouldFetchGatewayLicenseStatus(
                [{ license_code: "etl", checked_at: "2026-09-14T13:00:00+08:00" }],
                NOW,
            ),
        ).toBe(true)
    })

    it("fetches when gateway checked_at is missing or invalid", () => {
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(null), NOW)).toBe(true)
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(""), NOW)).toBe(true)
        expect(shouldFetchGatewayLicenseStatus(gatewayAt("not-a-date"), NOW)).toBe(true)
    })

    it("skips Gateway when checked_at is within one day", () => {
        const within = new Date(NOW - HOUR).toISOString()
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(within), NOW)).toBe(false)
        const exactlyOneDay = new Date(NOW - 24 * HOUR).toISOString()
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(exactlyOneDay), NOW)).toBe(false)
    })

    it("fetches Gateway when checked_at is older than one day", () => {
        const stale = new Date(NOW - 24 * HOUR - 1).toISOString()
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(stale), NOW)).toBe(true)
    })
})
