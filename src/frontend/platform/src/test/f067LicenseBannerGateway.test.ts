import { describe, expect, it } from "vitest"

import { shouldFetchGatewayLicenseStatus } from "@/layout/licenseBannerGateway"

const NOW = Date.parse("2026-09-14T14:00:00+08:00")
const HOUR = 60 * 60 * 1000

function gatewayAt(checkedAt: string | null) {
    return [{ license_code: "gateway", checked_at: checkedAt }]
}

describe("shouldFetchGatewayLicenseStatus", () => {
    it("skips Gateway when the deployment is not commercial", () => {
        expect(shouldFetchGatewayLicenseStatus([], NOW, false)).toBe(false)
        expect(shouldFetchGatewayLicenseStatus(undefined, NOW)).toBe(false)
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(null), NOW, false)).toBe(false)
    })

    it("fetches when there is no gateway row", () => {
        expect(shouldFetchGatewayLicenseStatus([], NOW, true)).toBe(true)
        expect(shouldFetchGatewayLicenseStatus(undefined, NOW, true)).toBe(true)
        expect(
            shouldFetchGatewayLicenseStatus(
                [{ license_code: "etl", checked_at: "2026-09-14T13:00:00+08:00" }],
                NOW,
                true,
            ),
        ).toBe(true)
    })

    it("fetches when gateway checked_at is missing or invalid", () => {
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(null), NOW, true)).toBe(true)
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(""), NOW, true)).toBe(true)
        expect(shouldFetchGatewayLicenseStatus(gatewayAt("not-a-date"), NOW, true)).toBe(true)
    })

    it("skips Gateway when checked_at is within one day", () => {
        const within = new Date(NOW - HOUR).toISOString()
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(within), NOW, true)).toBe(false)
        const exactlyOneDay = new Date(NOW - 24 * HOUR).toISOString()
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(exactlyOneDay), NOW, true)).toBe(false)
    })

    it("fetches Gateway when checked_at is older than one day", () => {
        const stale = new Date(NOW - 24 * HOUR - 1).toISOString()
        expect(shouldFetchGatewayLicenseStatus(gatewayAt(stale), NOW, true)).toBe(true)
    })
})
