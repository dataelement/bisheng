import { describe, expect, it } from "vitest"

import { buildLicenseBannerCopy, type AggregatedLicense } from "@/layout/licenseBannerCopy"

const NAMES: Record<string, string> = {
    gateway: "Gateway license",
    etl: "ETL license",
    dashboard: "Dashboard license",
}

function t(key: string, options?: Record<string, unknown>): string {
    if (key.startsWith("license.name.")) {
        return NAMES[key.slice("license.name.".length)] ?? key
    }
    if (key === "license.expiring") {
        return `${options?.name} will expire on ${options?.date} with ${options?.days} days remaining`
    }
    if (key === "license.expired") {
        return `${options?.name} expired on ${options?.date}`
    }
    if (key === "license.renewHint") {
        return "Contact the provider to renew."
    }
    return key
}

function license(partial: Partial<AggregatedLicense> & Pick<AggregatedLicense, "license_code" | "display_state">): AggregatedLicense {
    return {
        expire_date: "2026-09-30",
        days_remaining: 16,
        ...partial,
    }
}

describe("buildLicenseBannerCopy", () => {
    it("returns empty for normal and unknown", () => {
        expect(
            buildLicenseBannerCopy(
                [
                    license({ license_code: "gateway", display_state: "normal" }),
                    license({ license_code: "etl", display_state: "unknown" }),
                ],
                t,
            ),
        ).toBe("")
    })

    it("builds a complete expiring sentence for one item", () => {
        expect(
            buildLicenseBannerCopy(
                [license({ license_code: "etl", display_state: "expiring", expire_date: "2026-09-30", days_remaining: 16 })],
                t,
            ),
        ).toBe("ETL license will expire on 2026-09-30 with 16 days remaining。Contact the provider to renew.")
    })

    it("builds an expired sentence with the business name", () => {
        expect(
            buildLicenseBannerCopy(
                [license({ license_code: "gateway", display_state: "expired", expire_date: "2026-09-01" })],
                t,
            ),
        ).toBe("Gateway license expired on 2026-09-01。Contact the provider to renew.")
    })

    it("joins multiple items without a count summary", () => {
        const text = buildLicenseBannerCopy(
            [
                license({ license_code: "gateway", display_state: "expired" }),
                license({ license_code: "dashboard", display_state: "expiring", expire_date: "2026-09-30", days_remaining: 16 }),
            ],
            t,
        )
        expect(text).toContain("Gateway license expired on 2026-09-30")
        expect(text).toContain("Dashboard license will expire on 2026-09-30 with 16 days remaining")
        expect(text).toContain("；")
        expect(text).not.toContain("total")
        expect(text).toContain("Contact the provider to renew.")
        expect(text).not.toContain("Software license")
    })
})
