/**
 * Role quota parsing, serialization and validation.
 *
 * Extracted from Roles.tsx so the rules are unit-testable and so that adding a
 * quota dimension touches one place instead of a dozen call sites (state,
 * snapshot, open-create, open-edit, retry, submit, table column...).
 */

/** Knowledge-space total upload quota (GB); one decimal, inclusive bounds. */
export const KB_SPACE_FILE_GB_MIN = 0.1
export const KB_SPACE_FILE_GB_MAX = 999

/**
 * Display fallbacks for a role that has never had the key persisted.
 *
 * These mirror the backend `DEFAULT_ROLE_QUOTA`
 * (`role/domain/services/quota_service.py`) — a silent drift point: a role whose
 * `quota_config` lacks the key is enforced with the backend default, so the two
 * lists must stay in sync.
 */
export const ROLE_QUOTA_DEFAULT_FILE_GB = "500"
export const ROLE_QUOTA_DEFAULT_CHANNEL = "10"
export const ROLE_QUOTA_DEFAULT_SPACE_SUBSCRIBE = "100"
export const ROLE_QUOTA_DEFAULT_SPACE_CREATE = "50"

export interface RoleQuotaState {
  fileUnlimited: boolean
  fileGb: string
  channelUnlimited: boolean
  channelCount: string
  spaceSubscribeUnlimited: boolean
  spaceSubscribeCount: string
  spaceCreateUnlimited: boolean
  spaceCreateCount: string
}

type QuotaConfig = Record<string, unknown> | null | undefined

export function normalizeKnowledgeSpaceFileGb(raw: string): number | null {
  const n = Number(raw)
  if (!Number.isFinite(n)) return null
  const r = Math.round(n * 10) / 10
  if (r < KB_SPACE_FILE_GB_MIN || r > KB_SPACE_FILE_GB_MAX) return null
  if (Math.abs(r - n) > 1e-6) return null
  return r
}

export function formatKnowledgeSpaceGbInput(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return ROLE_QUOTA_DEFAULT_FILE_GB
  const r = Math.round(n * 10) / 10
  if (r < KB_SPACE_FILE_GB_MIN || r > KB_SPACE_FILE_GB_MAX) return ROLE_QUOTA_DEFAULT_FILE_GB
  return Number.isInteger(r) ? String(r) : r.toFixed(1)
}

/** Clamp and format after blur — allows odd drafts while typing, fixes display on blur. */
export function clampKnowledgeQuotaGbDisplay(raw: string): string {
  const t = raw.trim().replace(/，/g, ".")
  if (!t) return ROLE_QUOTA_DEFAULT_FILE_GB
  const n = Number(t)
  if (!Number.isFinite(n)) return ROLE_QUOTA_DEFAULT_FILE_GB
  const r = Math.round(n * 10) / 10
  const clamped = Math.max(KB_SPACE_FILE_GB_MIN, Math.min(KB_SPACE_FILE_GB_MAX, r))
  return Number.isInteger(clamped) ? String(clamped) : clamped.toFixed(1)
}

/** Read an integer count quota: `-1` means unlimited, a missing key falls back. */
function readCountQuota(raw: unknown, fallback: string): { unlimited: boolean; count: string } {
  const v = Number(raw ?? fallback)
  if (Number.isNaN(v)) return { unlimited: false, count: fallback }
  return { unlimited: v === -1, count: v >= 0 ? String(v) : fallback }
}

function toCountValue(unlimited: boolean, count: string): number {
  return unlimited ? -1 : Math.max(0, Number(count || 0))
}

export function createDefaultRoleQuota(): RoleQuotaState {
  return {
    fileUnlimited: false,
    fileGb: ROLE_QUOTA_DEFAULT_FILE_GB,
    channelUnlimited: false,
    channelCount: ROLE_QUOTA_DEFAULT_CHANNEL,
    spaceSubscribeUnlimited: false,
    spaceSubscribeCount: ROLE_QUOTA_DEFAULT_SPACE_SUBSCRIBE,
    spaceCreateUnlimited: false,
    spaceCreateCount: ROLE_QUOTA_DEFAULT_SPACE_CREATE,
  }
}

export function parseRoleQuota(quotaConfig: QuotaConfig): RoleQuotaState {
  const qc: Record<string, unknown> = quotaConfig || {}
  // knowledge_space_file is the one GB-valued quota and its historical default
  // is "unlimited": a missing key reads as -1, not as the display fallback.
  const rawFile = qc.knowledge_space_file
  const fileLimit = typeof rawFile === "number" ? rawFile : Number(rawFile ?? -1)
  const channel = readCountQuota(qc.channel, ROLE_QUOTA_DEFAULT_CHANNEL)
  const spaceSubscribe = readCountQuota(qc.knowledge_space_subscribe, ROLE_QUOTA_DEFAULT_SPACE_SUBSCRIBE)
  const spaceCreate = readCountQuota(qc.knowledge_space, ROLE_QUOTA_DEFAULT_SPACE_CREATE)

  return {
    fileUnlimited: fileLimit === -1,
    fileGb: fileLimit > 0 ? formatKnowledgeSpaceGbInput(fileLimit) : ROLE_QUOTA_DEFAULT_FILE_GB,
    channelUnlimited: channel.unlimited,
    channelCount: channel.count,
    spaceSubscribeUnlimited: spaceSubscribe.unlimited,
    spaceSubscribeCount: spaceSubscribe.count,
    spaceCreateUnlimited: spaceCreate.unlimited,
    spaceCreateCount: spaceCreate.count,
  }
}

/**
 * Merge the dialog's quota selection onto an existing `quota_config`.
 *
 * Only the four managed quota keys are written; everything else on `base`
 * (menu-approval flags, keys this UI does not know about) survives untouched.
 */
export function buildRoleQuotaConfig(
  state: RoleQuotaState,
  base: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    ...base,
    knowledge_space_file: state.fileUnlimited
      ? -1
      : (normalizeKnowledgeSpaceFileGb(state.fileGb) ?? KB_SPACE_FILE_GB_MIN),
    channel: toCountValue(state.channelUnlimited, state.channelCount),
    knowledge_space_subscribe: toCountValue(state.spaceSubscribeUnlimited, state.spaceSubscribeCount),
    knowledge_space: toCountValue(state.spaceCreateUnlimited, state.spaceCreateCount),
  }
}

/** Returns an i18n key describing the first invalid field, or null when valid. */
export function validateRoleQuota(state: RoleQuotaState): string | null {
  if (!state.fileUnlimited && normalizeKnowledgeSpaceFileGb(state.fileGb) === null) {
    return "system.knowledgeSpaceFileQuotaInvalid"
  }
  return null
}

/** Stable projection for the unsaved-changes snapshot (key order is fixed). */
export function serializeRoleQuotaSnapshot(state: RoleQuotaState): (string | boolean)[] {
  return [
    state.fileUnlimited,
    state.fileGb,
    state.channelUnlimited,
    state.channelCount,
    state.spaceSubscribeUnlimited,
    state.spaceSubscribeCount,
    state.spaceCreateUnlimited,
    state.spaceCreateCount,
  ]
}

/**
 * Label for a count quota in the role table. `unlimitedLabel` is passed in so
 * this module stays free of i18n plumbing.
 */
export function formatRoleQuotaCount(raw: unknown, fallback: string, unlimitedLabel: string): string {
  const v = Number(raw ?? fallback)
  if (Number.isNaN(v)) return "-"
  if (v === -1) return unlimitedLabel
  return String(v)
}

/** Label for the GB-valued upload quota in the role table. */
export function formatRoleQuotaGb(raw: unknown, unlimitedLabel: string): string {
  const v = typeof raw === "number" ? raw : Number(raw ?? -1)
  if (Number.isNaN(v)) return "-"
  if (v === -1) return unlimitedLabel
  const r = Math.round(v * 10) / 10
  return `${Number.isInteger(r) ? String(r) : r.toFixed(1)} GB`
}
