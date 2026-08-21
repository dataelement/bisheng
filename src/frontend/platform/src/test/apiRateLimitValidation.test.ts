import type { ApiRateLimitConfig } from "@/controllers/API/apiRateLimit"
import {
  findInvalidApiRateLimitRule,
  isValidApiRateLimitConfig,
  normalizeApiRateLimitConfig,
} from "@/pages/SystemPage/components/apiRateLimitValidation"
import { describe, expect, it } from "vitest"

function config(overrides: Partial<ApiRateLimitConfig> = {}): ApiRateLimitConfig {
  return {
    schema_version: 1,
    revision: 1,
    global: {
      limits: { second: 0, minute: 20, hour: null, day: null },
      message: "  busy  ",
    },
    routes: [],
    updated_at: null,
    updated_by: null,
    ...overrides,
  }
}

describe("API rate limit validation", () => {
  it("normalizes zero limits, messages, and non-method rules", () => {
    const normalized = normalizeApiRateLimitConfig(config({
      routes: [{
        id: "one",
        match_type: "PATH",
        method: "GET",
        path: " /api/v1/items/{item_id} ",
        limits: { second: 0, minute: null, hour: null, day: null },
        message: "  route busy  ",
      }],
    }))

    expect(normalized.global.limits.second).toBeNull()
    expect(normalized.global.message).toBe("busy")
    expect(normalized.routes[0]).toMatchObject({
      method: null,
      path: "/api/v1/items/{item_id}",
      message: "route busy",
    })
  })

  it("rejects duplicate route identities", () => {
    const routes = ["one", "two"].map((id) => ({
      id,
      match_type: "PATH" as const,
      method: null,
      path: "/api/v1/items/{item_id}",
      limits: { second: null, minute: null, hour: null, day: null },
      message: "",
    }))

    expect(findInvalidApiRateLimitRule(routes)).toBe(1)
  })

  it("rejects fractional and out-of-range limits", () => {
    expect(isValidApiRateLimitConfig(config({
      global: {
        limits: { second: 1.5, minute: 20, hour: null, day: null },
        message: "",
      },
    }))).toBe(false)
  })
})
