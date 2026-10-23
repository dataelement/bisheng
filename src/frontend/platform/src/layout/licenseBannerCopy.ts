export interface AggregatedLicense {
    license_code: string
    license_name?: string
    display_state: string
    expire_date?: string | null
    days_remaining?: number | null
}

export type LicenseCopyTranslate = (key: string, options?: Record<string, unknown>) => string

export function buildLicenseBannerCopy(
    licenses: AggregatedLicense[],
    t: LicenseCopyTranslate,
): string {
    const visible = licenses.filter(
        (item) => item.display_state === "expiring" || item.display_state === "expired",
    )
    if (!visible.length) {
        return ""
    }
    const parts = visible.map((item) => {
        const name = t(`license.name.${item.license_code}`)
        if (item.display_state === "expired") {
            return t("license.expired", { name, date: item.expire_date ?? "" })
        }
        return t("license.expiring", {
            name,
            date: item.expire_date ?? "",
            days: item.days_remaining ?? 0,
        })
    })
    return `${parts.join("；")}。${t("license.renewHint")}`
}
