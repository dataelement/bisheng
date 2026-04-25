import i18next from "i18next"

const SYSTEM_DEFAULT_TENANT_NAME = "Default Tenant"

/** Localize the system-seeded "Default Tenant" name; pass other names through. */
export function displayTenantName(name?: string | null): string {
  const value = (name || "").trim()
  if (!value) return ""
  if (value === SYSTEM_DEFAULT_TENANT_NAME) {
    return i18next.t("tenant.defaultName", {
      ns: "bs",
      defaultValue: SYSTEM_DEFAULT_TENANT_NAME,
    })
  }
  return value
}
