import copy from "./fixtures/f067LicenseBannerCopy.zh.json"
import { describe, expect, it } from "vitest"

import { buildLicenseBannerCopy, type AggregatedLicense } from "@/layout/licenseBannerCopy"

const NAMES: Record<string, string> = {
    gateway: copy.gatewayName,
    etl: copy.etlName,
    dashboard: copy.dashboardName,
}

function t(key: string, options?: Record<string, unknown>): string {
    if (key.startsWith("license.name.")) {
        return NAMES[key.slice("license.name.".length)] ?? key
    }
    if (key === "license.expiring") {
        return copy.expiring.replace('{{name}}', String(options?.name)).replace('{{date}}', String(options?.date)).replace('{{days}}', String(options?.days))
    }
    if (key === "license.expired") {
        return copy.expired.replace('{{name}}', String(options?.name)).replace('{{date}}', String(options?.date))
    }
    if (key === "license.renewHint") {
        return copy.renewHint
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
        ).toBe(copy.singleExpiring)
    })

    it("builds an expired sentence with the business name", () => {
        expect(
            buildLicenseBannerCopy(
                [license({ license_code: "gateway", display_state: "expired", expire_date: "2026-09-01" })],
                t,
            ),
        ).toBe(copy.singleExpired)
    })

    it("joins multiple items without a count summary", () => {
        const text = buildLicenseBannerCopy(
            [
                license({ license_code: "gateway", display_state: "expired" }),
                license({ license_code: "dashboard", display_state: "expiring", expire_date: "2026-09-30", days_remaining: 16 }),
            ],
            t,
        )
        expect(text).toContain(copy.multipleExpired)
        expect(text).toContain(copy.multipleExpiring)
        expect(text).toContain("；")
        expect(text).not.toContain(copy.countSummary)
        expect(text).toContain(copy.renewHint)
        expect(text).not.toContain(copy.genericLicenseName)
    })
})
