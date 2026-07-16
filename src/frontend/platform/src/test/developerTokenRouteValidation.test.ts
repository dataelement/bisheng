import type { DeveloperTokenRouteRule } from "@/controllers/API/developerToken"
import {
  findInvalidDeveloperTokenRouteRule,
  normalizeDeveloperTokenRouteWhitelist,
} from "@/pages/SystemPage/components/developerTokenRouteValidation"
import { describe, expect, it } from "vitest"

describe("developer token route validation", () => {
  it("normalizes valid route rules", () => {
    const rules = [
      { match_type: "METHOD_PATH", method: "get", path: " /api/v1/items/{item_id} " },
      { match_type: "PATH", method: null, path: "/api/v1/health" },
      { match_type: "PREFIX", method: null, path: "/api/v1/files/*" },
    ] as DeveloperTokenRouteRule[]

    expect(findInvalidDeveloperTokenRouteRule(rules)).toBeNull()
    expect(normalizeDeveloperTokenRouteWhitelist(rules)).toEqual([
      { match_type: "METHOD_PATH", method: "GET", path: "/api/v1/items/{item_id}" },
      { match_type: "PATH", method: null, path: "/api/v1/health" },
      { match_type: "PREFIX", method: null, path: "/api/v1/files/*" },
    ])
  })

  it.each([
    [[{ match_type: "METHOD_PATH", method: null, path: "/api/v1/items" }], "method"],
    [[{ match_type: "METHOD_PATH", method: "TRACE", path: "/api/v1/items" }], "method"],
    [[{ match_type: "PATH", method: "GET", path: "/api/v1/items" }], "method"],
    [[{ match_type: "PATH", method: null, path: "api/v1/items" }], "path"],
    [[{ match_type: "PATH", method: null, path: "/api/v1/items?q=1" }], "path"],
    [[{ match_type: "PREFIX", method: null, path: "/api/v1/items" }], "prefix"],
    [[{ match_type: "PREFIX", method: null, path: "/api/*/items/*" }], "prefix"],
  ])("rejects invalid route rules", (rules, reason) => {
    expect(findInvalidDeveloperTokenRouteRule(rules as DeveloperTokenRouteRule[])?.reason).toBe(reason)
  })

  it("accepts 200 rules and rejects normalized duplicates or 201 rules", () => {
    const maxRules = Array.from({ length: 200 }, (_, index) => ({
      match_type: "PATH" as const,
      method: null,
      path: `/api/v1/items/${index}`,
    }))
    const duplicates = [
      { match_type: "PATH", method: null, path: "/api/v1/items" },
      { match_type: "PATH", method: null, path: " /api/v1/items " },
    ] as DeveloperTokenRouteRule[]

    expect(findInvalidDeveloperTokenRouteRule(maxRules)).toBeNull()
    expect(findInvalidDeveloperTokenRouteRule(duplicates)?.reason).toBe("duplicate")
    expect(findInvalidDeveloperTokenRouteRule([...maxRules, {
      match_type: "PATH", method: null, path: "/api/v1/items/200",
    }])?.reason).toBe("tooMany")
  })
})
