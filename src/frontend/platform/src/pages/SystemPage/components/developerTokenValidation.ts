const RATE_LIMIT_INPUT_PATTERN = /^\d*$/
const RATE_LIMIT_CONTROL_KEYS = new Set([
  "Backspace", "Delete", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
  "Home", "End", "Tab", "Enter", "Escape",
])
const IP_WHITELIST_RULE_SPLIT_PATTERN = /[\s,;]+/
const CIDR_PREFIX_PATTERN = /^(0|[1-9]\d*)$/
const IPV4_SEGMENT_PATTERN = /^(0|[1-9]\d{0,2})$/

export function isRateLimitInputAllowed(value: string): boolean {
  return RATE_LIMIT_INPUT_PATTERN.test(value)
}

export function isRateLimitControlKey(key: string): boolean {
  return RATE_LIMIT_CONTROL_KEYS.has(key)
}

export function sanitizeRateLimitInput(value: string): string {
  return value.replace(/\D/g, "")
}

export function isRateLimitValueValid(value: string): boolean {
  const clean = value.trim()
  return clean === "" || RATE_LIMIT_INPUT_PATTERN.test(clean)
}

export function parseLimit(value: string): number | null {
  const clean = value.trim()
  if (!clean || !RATE_LIMIT_INPUT_PATTERN.test(clean)) return null
  const parsed = Number(clean)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function formatLimitInput(value?: number | null): string {
  return value == null ? "" : String(value)
}

export function splitIpWhitelistRules(value?: string | null): string[] {
  if (!value) return []
  return value.split(IP_WHITELIST_RULE_SPLIT_PATTERN).map((part) => part.trim()).filter(Boolean)
}

export function findInvalidIpWhitelistRule(value?: string | null): string | null {
  return splitIpWhitelistRules(value).find((rule) => !isValidIpRule(rule)) || null
}

function isValidIpRule(rule: string): boolean {
  return rule.includes("/") ? isValidIpNetwork(rule) : isValidIpAddress(rule)
}

function isValidIpNetwork(rule: string): boolean {
  const parts = rule.split("/")
  if (parts.length !== 2 || !parts[0] || !CIDR_PREFIX_PATTERN.test(parts[1])) return false
  const prefix = Number(parts[1])
  if (!Number.isInteger(prefix)) return false
  if (isValidIpv4Address(parts[0])) return prefix <= 32
  return isValidIpv6Address(parts[0]) && prefix <= 128
}

function isValidIpAddress(value: string): boolean {
  return isValidIpv4Address(value) || isValidIpv6Address(value)
}

function isValidIpv4Address(value: string): boolean {
  const parts = value.split(".")
  return parts.length === 4 && parts.every((part) => {
    if (!IPV4_SEGMENT_PATTERN.test(part)) return false
    const parsed = Number(part)
    return Number.isInteger(parsed) && parsed >= 0 && parsed <= 255
  })
}

function isValidIpv6Address(value: string): boolean {
  if (!value || !value.includes(":") || value.includes("[") || value.includes("]")) return false
  try {
    return new URL(`http://[${value}]/`).hostname.length > 2
  } catch {
    return false
  }
}
