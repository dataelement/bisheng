import type {
  DeveloperTokenFileSyncDynamicSource,
  DeveloperTokenFileSyncFolderDynamicSource,
  DeveloperTokenFileSyncFolderMode,
  DeveloperTokenFileSyncMode,
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule,
  DeveloperTokenFileSyncTargetDisplay,
} from "@/controllers/API/developerToken"

const CATEGORY_CODE_PATTERN = /^[A-Z0-9_]{1,16}$/
const SUBCATEGORY_CODE_PATTERN = /^[A-Z0-9_-]{1,16}$/
const BUSINESS_DOMAIN_CODE_PATTERN = /^[A-Z0-9_]{1,16}$/
const FOLDER_PATH_PATTERN = /^[^/\\]+(?:\/[^/\\]+)*$/

export type FileSyncRuleErrorField =
  | "category"
  | "subcategory"
  | "businessDomain"
  | "targetSpace"
  | "targetFolder"
  | "businessDomainTargetBinding"
  | "businessDomainDynamicSource"
  | "targetSpaceDynamicSource"
  | "targetFolderDynamicSource"

export type FileSyncRuleErrorReason = "required" | "invalid" | "stale" | "unbound"

export interface FileSyncRuleError {
  field: FileSyncRuleErrorField
  reason: FileSyncRuleErrorReason
}

export interface FileSyncRuleSummaryLabels {
  notConfigured: string
  businessDomain: string
  targetSpace: string
  targetFolder: string
  dynamicDepartment: string
  dynamicResponsiblePerson: string
  folderNone: string
  folderDynamicDepartmentName: string
  folderDynamicCallerMainDepartmentName: string
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

export function normalizeFolderPath(value?: string | null): string | null {
  const segments = (value ?? "")
    .replace(/\\/g, "/")
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean)
  if (!segments.length) return null
  return segments.join("/")
}

export function createEmptyFileSyncRule(): DeveloperTokenFileSyncRule {
  return {
    category: { code: "", subcategory_code: "" },
    business_domain: { mode: "fixed", code: null, dynamic_source: null },
    target_space: {
      mode: "fixed",
      knowledge_id: null,
      folder_id: null,
      dynamic_source: null,
      folder_mode: "none",
      folder_path: null,
      parent_folder_path: null,
      folder_dynamic_source: null,
    },
    dynamic_source: null,
  }
}

function inferFolderMode(targetSpace: DeveloperTokenFileSyncRule["target_space"]): DeveloperTokenFileSyncFolderMode {
  if (targetSpace.folder_mode && targetSpace.folder_mode !== "none") {
    return targetSpace.folder_mode
  }
  if (normalizeFolderPath(targetSpace.folder_path)) return "fixed"
  if (targetSpace.folder_id != null) return "fixed"
  return "none"
}

function normalizeTargetFolderFields(
  targetSpace: DeveloperTokenFileSyncRule["target_space"],
): DeveloperTokenFileSyncRule["target_space"] {
  const folderMode = inferFolderMode(targetSpace)
  if (folderMode === "none") {
    return {
      ...targetSpace,
      folder_mode: "none",
      folder_id: null,
      folder_path: null,
      parent_folder_path: null,
      folder_dynamic_source: null,
    }
  }
  if (folderMode === "fixed") {
    return {
      ...targetSpace,
      folder_mode: "fixed",
      folder_path: normalizeFolderPath(targetSpace.folder_path),
      folder_id: null,
      parent_folder_path: null,
      folder_dynamic_source: null,
    }
  }
  return {
    ...targetSpace,
    folder_mode: "dynamic",
    folder_id: null,
    folder_path: null,
    parent_folder_path: normalizeFolderPath(targetSpace.parent_folder_path),
    folder_dynamic_source: targetSpace.folder_dynamic_source ?? null,
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
    target_space: normalizeTargetFolderFields({
      ...migrated.target_space,
      knowledge_id: migrated.target_space.mode === "fixed"
        ? migrated.target_space.knowledge_id
        : null,
      dynamic_source: migrated.target_space.mode === "dynamic"
        ? migrated.target_space.dynamic_source ?? null
        : null,
    }),
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
      target_space: normalizeTargetFolderFields({
        mode,
        knowledge_id: mode === "fixed" ? rule.target_space.knowledge_id : null,
        folder_id: null,
        dynamic_source: mode === "dynamic" ? rule.target_space.dynamic_source ?? null : null,
        folder_mode: rule.target_space.folder_mode ?? "none",
        folder_path: rule.target_space.folder_mode === "fixed"
          ? rule.target_space.folder_path ?? null
          : mode === "dynamic"
            ? null
            : rule.target_space.folder_path ?? null,
        parent_folder_path: mode === "dynamic" && rule.target_space.folder_mode === "dynamic"
          ? null
          : rule.target_space.parent_folder_path ?? null,
        folder_dynamic_source: rule.target_space.folder_mode === "dynamic"
          ? rule.target_space.folder_dynamic_source ?? null
          : null,
      }),
    }
  return normalizeFileSyncRule(next) as DeveloperTokenFileSyncRule
}

export function changeFileSyncFolderMode(
  rule: DeveloperTokenFileSyncRule,
  folderMode: DeveloperTokenFileSyncFolderMode,
): DeveloperTokenFileSyncRule {
  const next: DeveloperTokenFileSyncRule = {
    ...rule,
    target_space: normalizeTargetFolderFields({
      ...rule.target_space,
      folder_mode: folderMode,
      folder_path: folderMode === "fixed" ? rule.target_space.folder_path ?? null : null,
      parent_folder_path: folderMode === "dynamic" ? rule.target_space.parent_folder_path ?? null : null,
      folder_dynamic_source: folderMode === "dynamic" ? rule.target_space.folder_dynamic_source ?? null : null,
    }),
  }
  return normalizeFileSyncRule(next) as DeveloperTokenFileSyncRule
}

function formatFolderDynamicSourceLabel(
  source: DeveloperTokenFileSyncFolderDynamicSource | null | undefined,
  labels: FileSyncRuleSummaryLabels,
): string {
  if (source === "department_name") return labels.folderDynamicDepartmentName
  if (source === "caller_main_department_name") return labels.folderDynamicCallerMainDepartmentName
  return "-"
}

function formatFolderSummary(
  rule: DeveloperTokenFileSyncRule,
  labels: FileSyncRuleSummaryLabels,
): string {
  const folderMode = inferFolderMode(rule.target_space)
  if (folderMode === "none") return labels.folderNone
  if (folderMode === "fixed") return rule.target_space.folder_path || "-"
  const parent = rule.target_space.parent_folder_path
  const child = formatFolderDynamicSourceLabel(rule.target_space.folder_dynamic_source, labels)
  return parent ? `${parent}/${child}` : child
}

function findSelectedTargetSpace(
  options: DeveloperTokenFileSyncOptions,
  knowledgeId: number | null | undefined,
) {
  if (!Number.isInteger(knowledgeId) || Number(knowledgeId) <= 0) return null
  return options.target_space_groups.data
    .flatMap((group) => group.spaces)
    .find((space) => space.id === knowledgeId) ?? null
}

function isFixedDomainSpaceBound(
  rule: DeveloperTokenFileSyncRule,
  options: DeveloperTokenFileSyncOptions,
): boolean {
  if (rule.business_domain.mode !== "fixed" || rule.target_space.mode !== "fixed") {
    return true
  }
  const domainCode = rule.business_domain.code
  const knowledgeId = rule.target_space.knowledge_id
  if (!domainCode || !Number.isInteger(knowledgeId) || Number(knowledgeId) <= 0) {
    return true
  }
  const domain = options.business_domains.find((item) => item.code === domainCode)
  const space = findSelectedTargetSpace(options, knowledgeId)
  if (!domain || !space) return true
  const domainSpaceIds = domain.space_ids ?? []
  const spaceDomainCodes = space.business_domain_codes ?? []
  return domainSpaceIds.includes(Number(knowledgeId))
    && spaceDomainCodes.includes(domainCode)
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
    if (
      targetDisplay?.stale
      && targetDisplay.knowledge_id === knowledgeId
      && targetDisplay.target_type === "root"
    ) {
      return { field: "targetSpace", reason: "stale" }
    }
    if (normalized.target_space.dynamic_source != null) {
      return { field: "targetSpaceDynamicSource", reason: "invalid" }
    }
    if (options && !isFixedDomainSpaceBound(normalized, options)) {
      return { field: "businessDomainTargetBinding", reason: "unbound" }
    }
  } else if (
    normalized.target_space.knowledge_id != null
    || normalized.target_space.folder_id != null
  ) {
    return { field: "targetSpace", reason: "invalid" }
  } else if (!normalized.target_space.dynamic_source) {
    return { field: "targetSpaceDynamicSource", reason: "required" }
  }

  const folderMode = inferFolderMode(normalized.target_space)
  if (folderMode === "fixed") {
    const folderPath = normalized.target_space.folder_path
    if (!folderPath) return { field: "targetFolder", reason: "required" }
    if (!FOLDER_PATH_PATTERN.test(folderPath)) {
      return { field: "targetFolder", reason: "invalid" }
    }
  } else if (folderMode === "dynamic") {
    const parentPath = normalized.target_space.parent_folder_path
    if (parentPath && !FOLDER_PATH_PATTERN.test(parentPath)) {
      return { field: "targetFolder", reason: "invalid" }
    }
    if (!normalized.target_space.folder_dynamic_source) {
      return { field: "targetFolderDynamicSource", reason: "required" }
    }
    if (normalized.target_space.mode === "dynamic" && parentPath) {
      return { field: "targetFolder", reason: "invalid" }
    }
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
  const folder = formatFolderSummary(normalized, labels)
  return [
    `${normalized.category.code}/${normalized.category.subcategory_code}`,
    `${labels.businessDomain}: ${domain}`,
    `${labels.targetSpace}: ${target}`,
    `${labels.targetFolder}: ${folder}`,
  ].join(" · ")
}

function formatFixedTarget(
  rule: DeveloperTokenFileSyncRule,
  labels: FileSyncRuleSummaryLabels,
  display?: DeveloperTokenFileSyncTargetDisplay | null,
): string {
  const knowledgeId = rule.target_space.knowledge_id
  const displayMatches = display && display.knowledge_id === knowledgeId
  if (!displayMatches) {
    return String(knowledgeId || "-")
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
