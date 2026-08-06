import type {
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule,
} from "@/controllers/API/developerToken"
import {
  changeFileSyncRuleMode,
  findInvalidFileSyncRule,
  formatFileSyncRuleSummary,
  normalizeFileSyncRule,
} from "@/pages/SystemPage/components/developerTokenFileSyncRuleValidation"
import { describe, expect, it } from "vitest"

const options: DeveloperTokenFileSyncOptions = {
  tenant_id: 2,
  user_id: 7,
  categories: [
    {
      code: "POLICY",
      label: "Policy",
      children: [{ code: "MGMT_POLICY", label: "Management policy" }],
    },
  ],
  business_domains: [{ code: "SAFETY", name: "Safety", space_ids: [118] }],
  target_space_groups: {
    data: [
      {
        space_type: "department",
        spaces: [{
          id: 118,
          name: "Safety space",
          selectable: true,
          has_children: true,
          business_domain_codes: ["SAFETY"],
        }],
      },
    ],
    has_more: false,
    next_cursor: null,
    page_size: 50,
  },
}

function rule(
  businessMode: "fixed" | "dynamic",
  targetMode: "fixed" | "dynamic",
  businessSource: DeveloperTokenFileSyncRule["business_domain"]["dynamic_source"] = "responsible_person_id",
  targetSource: DeveloperTokenFileSyncRule["target_space"]["dynamic_source"] = "responsible_person_id",
): DeveloperTokenFileSyncRule {
  return {
    category: { code: "POLICY", subcategory_code: "MGMT_POLICY" },
    business_domain: {
      mode: businessMode,
      code: businessMode === "fixed" ? "SAFETY" : null,
      dynamic_source: businessMode === "dynamic" ? businessSource : null,
    },
    target_space: {
      mode: targetMode,
      knowledge_id: targetMode === "fixed" ? 118 : null,
      folder_id: null,
      dynamic_source: targetMode === "dynamic" ? targetSource : null,
      folder_mode: "none",
      folder_path: null,
      parent_folder_path: null,
      folder_dynamic_source: null,
    },
    dynamic_source: null,
  }
}

describe("developer token file-sync rule validation", () => {
  it.each([
    ["fixed", "fixed"],
    ["fixed", "dynamic"],
    ["dynamic", "fixed"],
    ["dynamic", "dynamic"],
  ] as const)("accepts the %s/%s truth-table combination", (businessMode, targetMode) => {
    expect(findInvalidFileSyncRule(rule(businessMode, targetMode), options)).toBeNull()
  })

  it("normalizes codes, migrates legacy dynamic source, and removes fields that conflict with modes", () => {
    expect(normalizeFileSyncRule({
      category: { code: " policy ", subcategory_code: " mgmt_policy " },
      business_domain: { mode: "dynamic", code: " safety " },
      target_space: { mode: "fixed", knowledge_id: 118, folder_id: 4096 },
      dynamic_source: "department_id",
    })).toEqual({
      category: { code: "POLICY", subcategory_code: "MGMT_POLICY" },
      business_domain: { mode: "dynamic", code: null, dynamic_source: "department_id" },
      target_space: {
        mode: "fixed",
        knowledge_id: 118,
        folder_id: null,
        dynamic_source: null,
        folder_mode: "fixed",
        folder_path: null,
        parent_folder_path: null,
        folder_dynamic_source: null,
      },
      dynamic_source: null,
    })
  })

  it("accepts independent dynamic sources for business domain and target space", () => {
    expect(findInvalidFileSyncRule(
      rule("dynamic", "dynamic", "responsible_person_id", "department_id"),
      options,
    )).toBeNull()
  })

  it("reports stale category, business-domain, and knowledge-space references", () => {
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "fixed"),
      category: { code: "REMOVED", subcategory_code: "OLD" },
    }, options)).toEqual({ field: "category", reason: "stale" })
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "fixed"),
      business_domain: { mode: "fixed", code: "REMOVED" },
    }, options)).toEqual({ field: "businessDomain", reason: "stale" })
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "fixed"),
      target_space: {
        mode: "fixed",
        knowledge_id: 999,
        folder_mode: "fixed",
        folder_path: "Policies/Management",
      },
    }, options, {
      knowledge_id: 999,
      knowledge_name: null,
      target_type: "root",
      folder_path: [],
      stale: true,
    })).toEqual({ field: "targetSpace", reason: "stale" })
  })

  it("validates folder ids without assuming the current space page is exhaustive", () => {
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "fixed"),
      target_space: { mode: "fixed", knowledge_id: 999, folder_id: 4096, folder_mode: "fixed", folder_path: "A/B" },
    }, options)).toBeNull()
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "fixed"),
      target_space: {
        mode: "fixed",
        knowledge_id: 118,
        folder_mode: "fixed",
        folder_path: "   ",
      },
    }, options)).toEqual({ field: "targetFolder", reason: "required" })
  })

  it("reports unbound fixed business domain and target knowledge space", () => {
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "fixed"),
      business_domain: { mode: "fixed", code: "SAFETY" },
      target_space: {
        mode: "fixed",
        knowledge_id: 118,
        folder_id: null,
        folder_mode: "dynamic",
        parent_folder_path: "政策文件",
        folder_dynamic_source: "department_name",
      },
    }, {
      ...options,
      business_domains: [{ code: "SAFETY", name: "Safety", space_ids: [] }],
    })).toEqual({ field: "businessDomainTargetBinding", reason: "unbound" })
  })

  it("uses the same 16-character business-domain code contract as the backend", () => {
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "dynamic"),
      business_domain: { mode: "fixed", code: "BAD-CODE" },
    })).toEqual({ field: "businessDomain", reason: "invalid" })
  })

  it("accepts fixed folder path when target space is dynamic", () => {
    expect(findInvalidFileSyncRule({
      ...rule("dynamic", "dynamic"),
      target_space: {
        mode: "dynamic",
        knowledge_id: null,
        folder_id: null,
        dynamic_source: "responsible_person_id",
        folder_mode: "fixed",
        folder_path: "政策文件/管理制度",
        parent_folder_path: null,
        folder_dynamic_source: null,
      },
    }, options)).toBeNull()
  })

  it("clears incompatible fixed values and per-dimension dynamic sources on mode changes", () => {
    const dynamicBusiness = changeFileSyncRuleMode(rule("fixed", "fixed"), "businessDomain", "dynamic")
    expect(dynamicBusiness.business_domain).toEqual({
      mode: "dynamic",
      code: null,
      dynamic_source: null,
    })

    const fixedAgain = changeFileSyncRuleMode(
      {
        ...dynamicBusiness,
        business_domain: {
          mode: "dynamic",
          code: null,
          dynamic_source: "department_id",
        },
      },
      "businessDomain",
      "fixed",
    )
    expect(fixedAgain.business_domain.dynamic_source).toBeNull()

    const dynamicTarget = changeFileSyncRuleMode({
      ...rule("fixed", "fixed"),
      target_space: {
        mode: "fixed",
        knowledge_id: 118,
        folder_id: null,
        dynamic_source: null,
        folder_mode: "fixed",
        folder_path: "政策文件/管理制度",
        parent_folder_path: null,
        folder_dynamic_source: null,
      },
    }, "targetSpace", "dynamic")
    expect(dynamicTarget.target_space).toEqual({
      mode: "dynamic",
      knowledge_id: null,
      folder_id: null,
      dynamic_source: null,
      folder_mode: "fixed",
      folder_path: "政策文件/管理制度",
      parent_folder_path: null,
      folder_dynamic_source: null,
    })
  })

  it("formats localized configured and unconfigured summaries without option lookups", () => {
    const labels = {
      notConfigured: "Not configured",
      businessDomain: "Domain",
      targetSpace: "Space",
      targetFolder: "Folder",
      dynamicDepartment: "Dynamic(department)",
      dynamicResponsiblePerson: "Dynamic(responsible person)",
      folderNone: "Root",
      folderDynamicDepartmentName: "Dynamic(sync department name)",
      folderDynamicCallerMainDepartmentName: "Dynamic(bound user primary department name)",
    }

    expect(formatFileSyncRuleSummary(null, labels)).toBe("Not configured")
    expect(formatFileSyncRuleSummary(rule("fixed", "dynamic", "responsible_person_id", "department_id"), labels)).toBe(
      "POLICY/MGMT_POLICY · Domain: SAFETY · Space: Dynamic(department) · Folder: Root"
    )
    expect(formatFileSyncRuleSummary(
      rule("dynamic", "dynamic", "responsible_person_id", "department_id"),
      labels,
    )).toBe(
      "POLICY/MGMT_POLICY · Domain: Dynamic(responsible person) · Space: Dynamic(department) · Folder: Root"
    )
    expect(formatFileSyncRuleSummary({
      ...rule("fixed", "fixed"),
      target_space: { mode: "fixed", knowledge_id: 118, folder_id: 4096 },
    }, {
      ...labels,
      root: "Root",
      stale: "Unavailable",
    }, {
      knowledge_id: 118,
      knowledge_name: "Safety",
      target_type: "folder",
      folder_id: 4096,
      folder_path: [
        { id: 4000, name: "Policies" },
        { id: 4096, name: "Management" },
      ],
      stale: false,
    })).toContain("Safety / Policies / Management")
  })
})
