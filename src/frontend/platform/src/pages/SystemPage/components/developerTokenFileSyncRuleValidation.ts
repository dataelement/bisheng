import type {
  DeveloperTokenFileSyncMode,
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule,
} from "@/controllers/API/developerToken"

const CATEGORY_CODE_PATTERN = /^[A-Z0-9_]{1,16}$/
const SUBCATEGORY_CODE_PATTERN = /^[A-Z0-9_-]{1,16}$/
const BUSINESS_DOMAIN_CODE_PATTERN = /^[A-Z0-9_]{1,16}$/

export type FileSyncRuleErrorField =
  | "category"
  | "subcategory"
  | "businessDomain"
  | "targetSpace"
  | "dynamicSource"

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
}

export function createEmptyFileSyncRule(): DeveloperTokenFileSyncRule {
  return {
    category: { code: "", subcategory_code: "" },
    business_domain: { mode: "fixed", code: null },
    target_space: { mode: "fixed", knowledge_id: null },
    dynamic_source: null,
  }
}

export function normalizeFileSyncRule(
  rule?: DeveloperTokenFileSyncRule | null
): DeveloperTokenFileSyncRule | null {
  if (!rule) return null
  const dynamic = rule.business_domain.mode === "dynamic" || rule.target_space.mode === "dynamic"
  return {
    category: {
      code: rule.category.code.trim().toUpperCase(),
      subcategory_code: rule.category.subcategory_code.trim().toUpperCase(),
    },
    business_domain: {
      mode: rule.business_domain.mode,
      code: rule.business_domain.mode === "fixed"
        ? normalizeOptionalCode(rule.business_domain.code)
        : null,
    },
    target_space: {
      mode: rule.target_space.mode,
      knowledge_id: rule.target_space.mode === "fixed"
        ? rule.target_space.knowledge_id
        : null,
    },
    dynamic_source: dynamic ? rule.dynamic_source : null,
  }
}

export function changeFileSyncRuleMode(
  rule: DeveloperTokenFileSyncRule,
  field: "businessDomain" | "targetSpace",
  mode: DeveloperTokenFileSyncMode
): DeveloperTokenFileSyncRule {
  const next: DeveloperTokenFileSyncRule = field === "businessDomain"
    ? { ...rule, business_domain: { mode, code: mode === "fixed" ? rule.business_domain.code : null } }
    : { ...rule, target_space: { mode, knowledge_id: mode === "fixed" ? rule.target_space.knowledge_id : null } }
  return normalizeFileSyncRule(next) as DeveloperTokenFileSyncRule
}

export function findInvalidFileSyncRule(
  rule?: DeveloperTokenFileSyncRule | null,
  options?: DeveloperTokenFileSyncOptions | null
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
  } else if (normalized.business_domain.code != null) {
    return { field: "businessDomain", reason: "invalid" }
  }

  if (normalized.target_space.mode === "fixed") {
    const knowledgeId = normalized.target_space.knowledge_id
    if (!Number.isInteger(knowledgeId) || Number(knowledgeId) <= 0) {
      return { field: "targetSpace", reason: knowledgeId == null ? "required" : "invalid" }
    }
    const spacesExhaustive = options
      && options.knowledge_spaces.total <= options.knowledge_spaces.data.length
    if (
      spacesExhaustive
      && !options.knowledge_spaces.data.some((item) => item.id === knowledgeId)
    ) {
      return { field: "targetSpace", reason: "stale" }
    }
  } else if (normalized.target_space.knowledge_id != null) {
    return { field: "targetSpace", reason: "invalid" }
  }

  const dynamic = normalized.business_domain.mode === "dynamic" || normalized.target_space.mode === "dynamic"
  if (dynamic && !normalized.dynamic_source) return { field: "dynamicSource", reason: "required" }
  if (!dynamic && normalized.dynamic_source) return { field: "dynamicSource", reason: "invalid" }
  return null
}

export function formatFileSyncRuleSummary(
  rule: DeveloperTokenFileSyncRule | null | undefined,
  labels: FileSyncRuleSummaryLabels
): string {
  if (!rule) return labels.notConfigured
  const normalized = normalizeFileSyncRule(rule) as DeveloperTokenFileSyncRule
  const dynamicLabel = normalized.dynamic_source === "department_id"
    ? labels.dynamicDepartment
    : labels.dynamicResponsiblePerson
  const domain = normalized.business_domain.mode === "fixed"
    ? normalized.business_domain.code || "-"
    : dynamicLabel
  const target = normalized.target_space.mode === "fixed"
    ? String(normalized.target_space.knowledge_id || "-")
    : dynamicLabel
  return [
    `${normalized.category.code}/${normalized.category.subcategory_code}`,
    `${labels.businessDomain}: ${domain}`,
    `${labels.targetSpace}: ${target}`,
  ].join(" · ")
}

function normalizeOptionalCode(value?: string | null): string | null {
  const normalized = value?.trim().toUpperCase() || ""
  return normalized || null
}
