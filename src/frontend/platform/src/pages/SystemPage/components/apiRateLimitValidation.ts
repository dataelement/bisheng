import type {
  ApiRateLimitConfig,
  ApiRateLimitLimits,
  ApiRateLimitRouteRule,
} from "@/controllers/API/apiRateLimit"

export const MAX_API_RATE_LIMIT = 10_000_000
export const MAX_API_RATE_LIMIT_ROUTES = 200

export const EMPTY_LIMITS: ApiRateLimitLimits = {
  second: null,
  minute: null,
  hour: null,
  day: null,
}

export function normalizeApiRateLimitRule(
  rule: ApiRateLimitRouteRule
): ApiRateLimitRouteRule {
  return {
    ...rule,
    method: rule.match_type === "METHOD_PATH" ? rule.method : null,
    path: rule.path.trim(),
    limits: {
      second: normalizeLimit(rule.limits.second),
      minute: normalizeLimit(rule.limits.minute),
      hour: normalizeLimit(rule.limits.hour),
      day: normalizeLimit(rule.limits.day),
    },
    message: rule.message.trim(),
  }
}

export function normalizeLimit(value: number | null): number | null {
  return value === 0 ? null : value
}

export function isValidLimit(value: number | null): boolean {
  return value === null
    || (Number.isInteger(value) && value > 0 && value <= MAX_API_RATE_LIMIT)
}

export function normalizeApiRateLimitConfig(
  config: ApiRateLimitConfig
): ApiRateLimitConfig {
  const normalizeLimits = (limits: ApiRateLimitLimits): ApiRateLimitLimits => ({
    second: normalizeLimit(limits.second),
    minute: normalizeLimit(limits.minute),
    hour: normalizeLimit(limits.hour),
    day: normalizeLimit(limits.day),
  })
  return {
    ...config,
    global: {
      limits: normalizeLimits(config.global.limits),
      message: config.global.message.trim(),
    },
    routes: config.routes.map(normalizeApiRateLimitRule),
  }
}

export function findInvalidApiRateLimitRule(
  routes: ApiRateLimitRouteRule[]
): number | null {
  if (routes.length > MAX_API_RATE_LIMIT_ROUTES) return MAX_API_RATE_LIMIT_ROUTES
  const identities = new Set<string>()
  for (const [index, rule] of routes.entries()) {
    if (
      !rule.path.startsWith("/")
      || /[\s?#]/.test(rule.path)
      || (rule.match_type === "METHOD_PATH" && !rule.method)
      || (rule.match_type !== "METHOD_PATH" && rule.method !== null)
      || Object.values(rule.limits).some((value) => !isValidLimit(value))
    ) {
      return index
    }
    const identity = `${rule.match_type}:${rule.method || ""}:${rule.path}`
    if (identities.has(identity)) return index
    identities.add(identity)
  }
  return null
}

export function isValidApiRateLimitConfig(config: ApiRateLimitConfig): boolean {
  return Object.values(config.global.limits).every(isValidLimit)
    && findInvalidApiRateLimitRule(config.routes) === null
}
