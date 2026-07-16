import type { DeveloperTokenRouteRule } from "@/controllers/API/developerToken"

const ROUTE_METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
const ROUTE_MATCH_TYPES = new Set(["METHOD_PATH", "PATH", "PREFIX"])
export const MAX_DEVELOPER_TOKEN_ROUTE_RULES = 200

export type DeveloperTokenRouteRuleErrorReason =
  | "tooMany"
  | "matchType"
  | "method"
  | "path"
  | "prefix"
  | "duplicate"

export interface DeveloperTokenRouteRuleError {
  index: number
  reason: DeveloperTokenRouteRuleErrorReason
}

export function normalizeDeveloperTokenRouteWhitelist(
  rules?: DeveloperTokenRouteRule[] | null
): DeveloperTokenRouteRule[] {
  return (rules || []).map((rule) => ({
    match_type: rule.match_type.trim().toUpperCase() as DeveloperTokenRouteRule["match_type"],
    method: rule.match_type.trim().toUpperCase() === "METHOD_PATH"
      ? (rule.method || "").trim().toUpperCase()
      : null,
    path: rule.path.trim(),
  }))
}

export function findInvalidDeveloperTokenRouteRule(
  rules?: DeveloperTokenRouteRule[] | null
): DeveloperTokenRouteRuleError | null {
  if ((rules?.length || 0) > MAX_DEVELOPER_TOKEN_ROUTE_RULES) {
    return { index: MAX_DEVELOPER_TOKEN_ROUTE_RULES, reason: "tooMany" }
  }

  const normalized = normalizeDeveloperTokenRouteWhitelist(rules)
  const seen = new Set<string>()
  for (let index = 0; index < normalized.length; index += 1) {
    const rule = normalized[index]
    const rawMethod = (rules?.[index]?.method || "").trim()
    if (!ROUTE_MATCH_TYPES.has(rule.match_type)) return { index, reason: "matchType" }
    if (!isValidRoutePath(rule.path)) return { index, reason: "path" }
    if (rule.match_type === "METHOD_PATH") {
      if (!rule.method || !ROUTE_METHODS.has(rule.method) || rule.path.includes("*")) {
        return { index, reason: "method" }
      }
    } else if (rawMethod) {
      return { index, reason: "method" }
    } else if (rule.match_type === "PATH" && rule.path.includes("*")) {
      return { index, reason: "path" }
    } else if (
      rule.match_type === "PREFIX"
      && (!rule.path.endsWith("/*") || (rule.path.match(/\*/g) || []).length !== 1)
    ) {
      return { index, reason: "prefix" }
    }

    const key = `${rule.match_type}\u0000${rule.method || ""}\u0000${rule.path}`
    if (seen.has(key)) return { index, reason: "duplicate" }
    seen.add(key)
  }
  return null
}

function isValidRoutePath(path: string): boolean {
  return path.startsWith("/") && !/[\s?#]/.test(path)
}
