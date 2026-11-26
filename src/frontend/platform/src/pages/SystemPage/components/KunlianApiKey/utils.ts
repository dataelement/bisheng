import {
  KUNLIAN_ALL_TENANTS_WILDCARD,
  type KunlianApiKeyCapability,
  type KunlianApiKeyItem,
} from "@/types/api/kunlianApiKey";

export type KunlianKeyStatus = "active" | "revoked" | "expired";

const TIMEZONE_SUFFIX_RE = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;
const TENANT_SPLIT_RE = /[,\uFF0C;\uFF1B\s]+/;
const MAX_TENANT_ID_LENGTH = 128;

/**
 * Backend DateTime columns store naive UTC timestamps without a trailing Z.
 * Normalize them to explicit UTC ISO-8601 before passing to Date constructors.
 */
export function normalizeUtcIso(
  iso: string | null | undefined,
): string | null {
  if (!iso) return null;
  const trimmed = iso.trim();
  if (!trimmed) return null;
  if (TIMEZONE_SUFFIX_RE.test(trimmed)) return trimmed;
  return `${trimmed}Z`;
}

export function parseBackendUtcDate(
  iso: string | null | undefined,
): Date | null {
  const normalized = normalizeUtcIso(iso);
  if (!normalized) return null;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function getKunlianKeyStatus(
  item: Pick<KunlianApiKeyItem, "revoked_at" | "expires_at">,
  nowMs = Date.now(),
): KunlianKeyStatus {
  if (item.revoked_at) return "revoked";
  const expiresAt = parseBackendUtcDate(item.expires_at);
  if (expiresAt && expiresAt.getTime() <= nowMs) return "expired";
  return "active";
}

export function isAllTenantsScope(tenantIds: string[]): boolean {
  return (
    tenantIds.length === 1 && tenantIds[0] === KUNLIAN_ALL_TENANTS_WILDCARD
  );
}

export function parseTenantIdsInput(raw: string): {
  valid: string[];
  tooLong: string[];
  hasWildcard: boolean;
} {
  const seen = new Set<string>();
  const valid: string[] = [];
  const tooLong: string[] = [];
  let hasWildcard = false;

  for (const part of raw.split(TENANT_SPLIT_RE)) {
    const token = part.trim();
    if (!token || seen.has(token)) continue;
    seen.add(token);
    if (token === KUNLIAN_ALL_TENANTS_WILDCARD) {
      hasWildcard = true;
    } else if (token.length > MAX_TENANT_ID_LENGTH) {
      tooLong.push(token);
    } else {
      valid.push(token);
    }
  }

  return { valid, tooLong, hasWildcard };
}

export function mergeUniqueTenants(
  existing: string[],
  additions: string[],
): string[] {
  const seen = new Set(existing);
  const next = [...existing];
  for (const item of additions) {
    if (!seen.has(item)) {
      seen.add(item);
      next.push(item);
    }
  }
  return next;
}

export function sameStringSet(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((value) => rightSet.has(value));
}

export function sameTimestamp(
  left: string | null | undefined,
  right: string | null | undefined,
): boolean {
  const leftDate = parseBackendUtcDate(left);
  const rightDate = parseBackendUtcDate(right);
  if (!leftDate && !rightDate) return true;
  if (!leftDate || !rightDate) return false;
  return leftDate.getTime() === rightDate.getTime();
}

export function isValidCapabilityList(
  values: KunlianApiKeyCapability[],
): boolean {
  return values.length > 0;
}

export function buildKunlianVerifyCommand(
  origin: string,
  apiKey: string,
): string {
  return [
    `curl "${origin}/api/v2/kunlian/workflows?user_account=<USER_ACCOUNT>"`,
    `  -H "Authorization: Bearer ${apiKey}"`,
  ].join(" \\\n");
}
