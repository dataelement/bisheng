import { describe, expect, it } from "vitest"

import {
  findInvalidIpWhitelistRule,
  formatLimitInput,
  isRateLimitInputAllowed,
  isRateLimitValueValid,
  parseLimit,
  sanitizeRateLimitInput,
  splitIpWhitelistRules,
} from "@/pages/SystemPage/components/developerTokenValidation"

describe("developer token validation", () => {
  it("accepts empty and multi-rule IP whitelist values", () => {
    expect(findInvalidIpWhitelistRule("")).toBeNull()
    expect(findInvalidIpWhitelistRule("10.0.0.1\n192.168.1.0/24,2001:db8::1;2001:db8::/64")).toBeNull()
  })

  it("returns the first invalid IP whitelist rule", () => {
    expect(findInvalidIpWhitelistRule("10.0.0.1 not-an-ip 192.168.1.0/24")).toBe("not-an-ip")
    expect(findInvalidIpWhitelistRule("10.0.0.999")).toBe("10.0.0.999")
    expect(findInvalidIpWhitelistRule("192.168.1.0/33")).toBe("192.168.1.0/33")
    expect(findInvalidIpWhitelistRule("2001:db8::/129")).toBe("2001:db8::/129")
  })

  it("splits IP whitelist rules like the backend", () => {
    expect(splitIpWhitelistRules("10.0.0.1\n192.168.1.0/24, 2001:db8::1;2001:db8::/64")).toEqual([
      "10.0.0.1",
      "192.168.1.0/24",
      "2001:db8::1",
      "2001:db8::/64",
    ])
  })

  it("keeps rate-limit validation integer-only", () => {
    expect(isRateLimitInputAllowed("123")).toBe(true)
    expect(isRateLimitValueValid("")).toBe(true)
    expect(isRateLimitValueValid("0")).toBe(true)
    expect(isRateLimitValueValid("1.5")).toBe(false)
    expect(sanitizeRateLimitInput("a1.5")).toBe("15")
    expect(parseLimit("0")).toBeNull()
    expect(parseLimit("20")).toBe(20)
    expect(formatLimitInput(null)).toBe("")
  })
})
