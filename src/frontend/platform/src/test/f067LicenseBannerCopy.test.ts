import { describe, expect, it } from "vitest"

import { buildLicenseBannerCopy, type AggregatedLicense } from "@/layout/licenseBannerCopy"

const NAMES: Record<string, string> = {
    gateway: "Gateway 授权",
    etl: "ETL 授权",
    dashboard: "商业版看板授权",
}

function t(key: string, options?: Record<string, unknown>): string {
    if (key.startsWith("license.name.")) {
        return NAMES[key.slice("license.name.".length)] ?? key
    }
    if (key === "license.expiring") {
        return `${options?.name}将于 ${options?.date} 到期，剩余 ${options?.days} 天`
    }
    if (key === "license.expired") {
        return `${options?.name}已于 ${options?.date} 过期`
    }
    if (key === "license.renewHint") {
        return "请联系授权提供方续期。"
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
        ).toBe("ETL 授权将于 2026-09-30 到期，剩余 16 天。请联系授权提供方续期。")
    })

    it("builds an expired sentence with the business name", () => {
        expect(
            buildLicenseBannerCopy(
                [license({ license_code: "gateway", display_state: "expired", expire_date: "2026-09-01" })],
                t,
            ),
        ).toBe("Gateway 授权已于 2026-09-01 过期。请联系授权提供方续期。")
    })

    it("joins multiple items without a count summary", () => {
        const text = buildLicenseBannerCopy(
            [
                license({ license_code: "gateway", display_state: "expired" }),
                license({ license_code: "dashboard", display_state: "expiring", expire_date: "2026-09-30", days_remaining: 16 }),
            ],
            t,
        )
        expect(text).toContain("Gateway 授权已于 2026-09-30 过期")
        expect(text).toContain("商业版看板授权将于 2026-09-30 到期，剩余 16 天")
        expect(text).toContain("；")
        expect(text).not.toContain("共")
        expect(text).toContain("请联系授权提供方续期。")
        expect(text).not.toContain("软件授权")
    })
})
