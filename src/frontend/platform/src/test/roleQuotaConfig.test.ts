import { describe, expect, it } from "vitest"

import {
  buildRoleQuotaConfig,
  createDefaultRoleQuota,
  formatRoleQuotaCount,
  formatRoleQuotaGb,
  parseRoleQuota,
  ROLE_QUOTA_DEFAULT_CHANNEL,
  serializeRoleQuotaSnapshot,
  validateRoleQuota,
} from "@/pages/SystemPage/components/roleQuotaConfig"

describe("parseRoleQuota", () => {
  it("falls back to the backend defaults when a key was never saved", () => {
    const quota = parseRoleQuota({})
    // Mirrors DEFAULT_ROLE_QUOTA in quota_service.py.
    expect(quota.channelCount).toBe("10")
    expect(quota.spaceSubscribeCount).toBe("100")
    expect(quota.spaceCreateCount).toBe("50")
    expect(quota.channelUnlimited).toBe(false)
    expect(quota.spaceCreateUnlimited).toBe(false)
  })

  it("treats a missing upload quota as unlimited, unlike the count quotas", () => {
    expect(parseRoleQuota({}).fileUnlimited).toBe(true)
    expect(parseRoleQuota(null).fileUnlimited).toBe(true)
  })

  it("reads -1 as unlimited on every count quota", () => {
    const quota = parseRoleQuota({ channel: -1, knowledge_space: -1, knowledge_space_subscribe: -1 })
    expect(quota.channelUnlimited).toBe(true)
    expect(quota.spaceCreateUnlimited).toBe(true)
    expect(quota.spaceSubscribeUnlimited).toBe(true)
  })

  it("keeps a configured space-creation limit", () => {
    expect(parseRoleQuota({ knowledge_space: 2 }).spaceCreateCount).toBe("2")
    expect(parseRoleQuota({ knowledge_space: 0 }).spaceCreateCount).toBe("0")
  })

  it("formats a decimal upload quota for the input", () => {
    expect(parseRoleQuota({ knowledge_space_file: 12.5 }).fileGb).toBe("12.5")
    expect(parseRoleQuota({ knowledge_space_file: 500 }).fileGb).toBe("500")
  })
})

describe("buildRoleQuotaConfig", () => {
  it("writes all four managed quota keys", () => {
    const config = buildRoleQuotaConfig(createDefaultRoleQuota())
    expect(config).toMatchObject({
      knowledge_space_file: 500,
      channel: 10,
      knowledge_space: 50,
      knowledge_space_subscribe: 100,
    })
  })

  it("serializes unlimited as -1", () => {
    const quota = { ...createDefaultRoleQuota(), spaceCreateUnlimited: true, fileUnlimited: true }
    const config = buildRoleQuotaConfig(quota)
    expect(config.knowledge_space).toBe(-1)
    expect(config.knowledge_space_file).toBe(-1)
  })

  it("never lets a count go negative", () => {
    const quota = { ...createDefaultRoleQuota(), spaceCreateCount: "-7" }
    expect(buildRoleQuotaConfig(quota).knowledge_space).toBe(0)
  })

  it("preserves unrelated keys on the existing config", () => {
    const config = buildRoleQuotaConfig(createDefaultRoleQuota(), {
      menu_approval_mode: true,
      some_future_key: "keep me",
    })
    expect(config.menu_approval_mode).toBe(true)
    expect(config.some_future_key).toBe("keep me")
  })

  it("round-trips through parseRoleQuota", () => {
    const original = { ...createDefaultRoleQuota(), spaceCreateCount: "7", channelUnlimited: true }
    expect(parseRoleQuota(buildRoleQuotaConfig(original))).toMatchObject({
      spaceCreateCount: "7",
      channelUnlimited: true,
    })
  })
})

describe("validateRoleQuota", () => {
  it("accepts one decimal place within bounds", () => {
    expect(validateRoleQuota({ ...createDefaultRoleQuota(), fileGb: "0.1" })).toBeNull()
    expect(validateRoleQuota({ ...createDefaultRoleQuota(), fileGb: "999" })).toBeNull()
  })

  it("rejects out-of-range or over-precise upload quotas", () => {
    for (const fileGb of ["0", "1000", "1.25", "abc", ""]) {
      expect(validateRoleQuota({ ...createDefaultRoleQuota(), fileGb })).toBe(
        "system.knowledgeSpaceFileQuotaInvalid",
      )
    }
  })

  it("skips validation when the upload quota is unlimited", () => {
    expect(validateRoleQuota({ ...createDefaultRoleQuota(), fileUnlimited: true, fileGb: "nope" })).toBeNull()
  })
})

describe("snapshot and table labels", () => {
  it("changes the snapshot when any quota field changes", () => {
    const base = createDefaultRoleQuota()
    const changed = { ...base, spaceCreateCount: "9" }
    expect(serializeRoleQuotaSnapshot(changed)).not.toEqual(serializeRoleQuotaSnapshot(base))
  })

  it("labels counts, unlimited and missing values", () => {
    expect(formatRoleQuotaCount(5, ROLE_QUOTA_DEFAULT_CHANNEL, "Unlimited")).toBe("5")
    expect(formatRoleQuotaCount(-1, ROLE_QUOTA_DEFAULT_CHANNEL, "Unlimited")).toBe("Unlimited")
    expect(formatRoleQuotaCount(undefined, ROLE_QUOTA_DEFAULT_CHANNEL, "Unlimited")).toBe("10")
    expect(formatRoleQuotaCount("oops", ROLE_QUOTA_DEFAULT_CHANNEL, "Unlimited")).toBe("-")
  })

  it("labels GB quotas", () => {
    expect(formatRoleQuotaGb(12.5, "Unlimited")).toBe("12.5 GB")
    expect(formatRoleQuotaGb(-1, "Unlimited")).toBe("Unlimited")
    expect(formatRoleQuotaGb(undefined, "Unlimited")).toBe("Unlimited")
  })
})
