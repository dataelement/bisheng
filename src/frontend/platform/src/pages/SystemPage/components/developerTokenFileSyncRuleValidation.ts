import type {
  DeveloperTokenFileSyncDynamicSource,
  DeveloperTokenFileSyncMode,
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule,
  DeveloperTokenFileSyncTargetDisplay,
} from "@/controllers/API/developerToken"

const CATEGORY_CODE_PATTERN = /^[A-Z0-9_]{1,16}$/
const SUBCATEGORY_CODE_PATTERN = /^[A-Z0-9_-]{1,16}$/
const BUSINESS_DOMAIN_CODE_PATTERN = /^[A-Z0-9_]{1,16}$/

export type FileSyncRuleErrorField =
  | "category"
  | "subcategory"
  | "businessDomain"
  | "targetSpace"
  | "businessDomainDynamicSource"
  | "targetSpaceDynamicSource"

export type FileSyncRuleErrorReason = "required" | "invalid" | "stale"

export interface FileSyncRuleError {
  field: FileSyncRuleErrorField
  reason: FileSyncRuleErrorReason
}

export interface FileSyncRuleSummaryLabels {
  notConfigured: string
  businessDomain: string
  targetSpace: string
  dynamicDepartment: string
  dynamicResponsiblePerson: string
  root?: string
  stale?: string
}

function migrateLegacyDynamicSource(rule: DeveloperTokenFileSyncRule): DeveloperTokenFileSyncRule {
  const legacy = rule.dynamic_source
  if (!legacy) return rule
  return {
    ...rule,
    business_domain: rule.business_domain.mode === "dynamic" && !rule.business_domain.dynamic_source
      ? { ...rule.business_domain, dynamic_source: legacy }
      : rule.business_domain,
    target_space: rule.target_space.mode === "dynamic" && !rule.target_space.dynamic_source
      ? { ...rule.target_space, dynamic_source: legacy }
      : rule.target_space,
    dynamic_source: null,
  }
}

function formatDynamicSourceLabel(
  source: DeveloperTokenFileSyncDynamicSource | null | undefined,
  labels: FileSyncRuleSummaryLabels,
): string {
  if (source === "department_id") return labels.dynamicDepartment
  if (source === "responsible_person_id") return labels.dynamicResponsiblePerson
  return "-"
}

export function createEmptyFileSyncRule(): DeveloperTokenFileSyncRule {
  return {
    category: { code: "", subcategory_code: "" },
    business_domain: { mode: "fixed", code: null, dynamic_source: null },
    target_space: { mode: "fixed", knowledge_id: null, folder_id: null, dynamic_source: null },
    dynamic_source: null,
  }
}

export function normalizeFileSyncRule(
  rule?: DeveloperTokenFileSyncRule | null
): DeveloperTokenFileSyncRule | null {
  if (!rule) return null
  const migrated = migrateLegacyDynamicSource(rule)
  return {
    category: {
      code: migrated.category.code.trim().toUpperCase(),
      subcategory_code: migrated.category.subcategory_code.trim().toUpperCase(),
    },
    business_domain: {
      mode: migrated.business_domain.mode,
      code: migrated.business_domain.mode === "fixed"
        ? normalizeOptionalCode(migrated.business_domain.code)
        : null,
      dynamic_source: migrated.business_domain.mode === "dynamic"
        ? migrated.business_domain.dynamic_source ?? null
        : null,
    },
    target_space: {
      mode: migrated.target_space.mode,
      knowledge_id: migrated.target_space.mode === "fixed"
        ? migrated.target_space.knowledge_id
        : null,
      folder_id: migrated.target_space.mode === "fixed"
        ? migrated.target_space.folder_id ?? null
        : null,
      dynamic_source: migrated.target_space.mode === "dynamic"
        ? migrated.target_space.dynamic_source ?? null
        : null,
    },
    dynamic_source: null,
  }
}

export function changeFileSyncRuleMode(
  rule: DeveloperTokenFileSyncRule,
  field: "businessDomain" | "targetSpace",
  mode: DeveloperTokenFileSyncMode
): DeveloperTokenFileSyncRule {
  const next: DeveloperTokenFileSyncRule = field === "businessDomain"
    ? {
      ...rule,
      business_domain: {
        mode,
        code: mode === "fixed" ? rule.business_domain.code : null,
        dynamic_source: mode === "dynamic" ? rule.business_domain.dynamic_source ?? null : null,
      },
    }
    : {
      ...rule,
      target_space: {
        mode,
        knowledge_id: mode === "fixed" ? rule.target_space.knowledge_id : null,
        folder_id: mode === "fixed" ? rule.target_space.folder_id ?? null : null,
        dynamic_source: mode === "dynamic" ? rule.target_space.dynamic_source ?? null : null,
      },
    }
  return normalizeFileSyncRule(next) as DeveloperTokenFileSyncRule
}

export function findInvalidFileSyncRule(
  rule?: DeveloperTokenFileSyncRule | null,
  options?: DeveloperTokenFileSyncOptions | null,
  targetDisplay?: DeveloperTokenFileSyncTargetDisplay | null,
): FileSyncRuleError | null {
  if (!rule) return null
  const normalized = normalizeFileSyncRule(rule) as DeveloperTokenFileSyncRule
  const category = normalized.category
  if (!category.code) return { field: "category", reason: "required" }
  if (!CATEGORY_CODE_PATTERN.test(category.code)) return { field: "category", reason: "invalid" }
  if (!category.subcategory_code) return { field: "subcategory", reason: "required" }
  if (!SUBCATEGORY_CODE_PATTERN.test(category.subcategory_code)) {
    return { field: "subcategory", reason: "invalid" }
  }

  if (options) {
    const categoryOption = options.categories.find((item) => item.code === category.code)
    if (!categoryOption) return { field: "category", reason: "stale" }
    if (!categoryOption.children.some((item) => item.code === category.subcategory_code)) {
      return { field: "subcategory", reason: "stale" }
    }
  }

  if (normalized.business_domain.mode === "fixed") {
    const code = normalized.business_domain.code
    if (!code) return { field: "businessDomain", reason: "required" }
    if (!BUSINESS_DOMAIN_CODE_PATTERN.test(code)) {
      return { field: "businessDomain", reason: "invalid" }
    }
    if (options && !options.business_domains.some((item) => item.code === code)) {
      return { field: "businessDomain", reason: "stale" }
    }
    if (normalized.business_domain.dynamic_source != null) {
      return { field: "businessDomainDynamicSource", reason: "invalid" }
    }
  } else {
    if (normalized.business_domain.code != null) {
      return { field: "businessDomain", reason: "invalid" }
    }
    if (!normalized.business_domain.dynamic_source) {
      return { field: "businessDomainDynamicSource", reason: "required" }
    }
  }

  if (normalized.target_space.mode === "fixed") {
    const knowledgeId = normalized.target_space.knowledge_id
    if (!Number.isInteger(knowledgeId) || Number(knowledgeId) <= 0) {
      return { field: "targetSpace", reason: knowledgeId == null ? "required" : "invalid" }
    }
    const folderId = normalized.target_space.folder_id
    if (folderId != null && (!Number.isInteger(folderId) || folderId <= 0)) {
      return { field: "targetSpace", reason: "invalid" }
    }
    if (
      targetDisplay?.stale
      && targetDisplay.knowledge_id === knowledgeId
      && (targetDisplay.folder_id ?? null) === folderId
    ) {
      return { field: "targetSpace", reason: "stale" }
    }
    if (normalized.target_space.dynamic_source != null) {
      return { field: "targetSpaceDynamicSource", reason: "invalid" }
    }
  } else if (
    normalized.target_space.knowledge_id != null
    || normalized.target_space.folder_id != null
  ) {
    return { field: "targetSpace", reason: "invalid" }
  } else if (!normalized.target_space.dynamic_source) {
    return { field: "targetSpaceDynamicSource", reason: "required" }
  }

  if (normalized.dynamic_source) return { field: "businessDomainDynamicSource", reason: "invalid" }
  return null
}

export function formatFileSyncRuleSummary(
  rule: DeveloperTokenFileSyncRule | null | undefined,
  labels: FileSyncRuleSummaryLabels,
  targetDisplay?: DeveloperTokenFileSyncTargetDisplay | null,
): string {
  if (!rule) return labels.notConfigured
  const normalized = normalizeFileSyncRule(rule) as DeveloperTokenFileSyncRule
  const domain = normalized.business_domain.mode === "fixed"
    ? normalized.business_domain.code || "-"
    : formatDynamicSourceLabel(normalized.business_domain.dynamic_source, labels)
  const target = normalized.target_space.mode === "fixed"
    ? formatFixedTarget(normalized, labels, targetDisplay)
    : formatDynamicSourceLabel(normalized.target_space.dynamic_source, labels)
  return [
    `${normalized.category.code}/${normalized.category.subcategory_code}`,
    `${labels.businessDomain}: ${domain}`,
    `${labels.targetSpace}: ${target}`,
  ].join(" · ")
}

function formatFixedTarget(
  rule: DeveloperTokenFileSyncRule,
  labels: FileSyncRuleSummaryLabels,
  display?: DeveloperTokenFileSyncTargetDisplay | null,
): string {
  const knowledgeId = rule.target_space.knowledge_id
  const folderId = rule.target_space.folder_id
  const displayMatches = display
    && display.knowledge_id === knowledgeId
    && (display.folder_id ?? null) === (folderId ?? null)
  if (!displayMatches) {
    return folderId == null ? String(knowledgeId || "-") : `${knowledgeId}/${folderId}`
  }
  const segments = [display.knowledge_name || String(display.knowledge_id)]
  if (display.target_type === "root") segments.push(labels.root || "Root")
  else segments.push(...display.folder_path.map((item) => item.name))
  const suffix = display.stale && labels.stale ? ` (${labels.stale})` : ""
  return `${segments.join(" / ")}${suffix}`
}

function normalizeOptionalCode(value?: string | null): string | null {
  const normalized = value?.trim().toUpperCase() || ""
  return normalized || null
}
