import type {
  ApiKeyItem,
  ServiceAccountResourceGrant,
} from "@/types/api/openApi"
import { formatDate } from "@/util/utils"

export const RESOURCE_GRANT_FILTER_ALL = "all"

export const SERVICE_ACCOUNT_RESOURCE_TYPES = [
  "knowledge_library",
  "knowledge_space",
  "assistant",
  "workflow",
] as const

export const SERVICE_ACCOUNT_PERMISSION_TIERS = [
  "viewer",
  "editor",
  "manager",
] as const

export type ServiceAccountPermissionTier =
  (typeof SERVICE_ACCOUNT_PERMISSION_TIERS)[number]

export function isServiceAccountPermissionTier(
  value: string,
): value is ServiceAccountPermissionTier {
  return SERVICE_ACCOUNT_PERMISSION_TIERS.some((key) => key === value)
}

export function getRequiredScope(grant: ServiceAccountResourceGrant) {
  if (!isServiceAccountPermissionTier(grant.model_key)) return null
  const readOnly = grant.model_key === "viewer"
  if (
    grant.resource_type === "knowledge_library" ||
    grant.resource_type === "knowledge_space"
  ) {
    return readOnly ? "knowledge:read" : "knowledge:write"
  }
  if (grant.resource_type === "assistant") {
    return readOnly ? "assistant:read" : "assistant:invoke"
  }
  if (grant.resource_type === "workflow") {
    return readOnly ? "workflow:read" : "workflow:invoke"
  }
  return null
}

export function isServiceAccountGrantEffective(
  grant: ServiceAccountResourceGrant,
  keys: ApiKeyItem[],
) {
  const requiredScope = getRequiredScope(grant)
  if (!requiredScope) return false
  return keys.some(
    (key) =>
      key.is_valid &&
      !key.scopes.includes("delegate") &&
      key.scopes.includes(requiredScope),
  )
}

export function formatServiceAccountGrantTime(value: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : formatDate(date, "yyyy-MM-dd HH:mm")
}
