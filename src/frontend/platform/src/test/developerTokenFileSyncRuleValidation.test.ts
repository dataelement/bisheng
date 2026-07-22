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
  business_domains: [{ code: "SAFETY", name: "Safety" }],
  target_space_groups: {
    data: [
      {
        space_type: "department",
        spaces: [{ id: 118, name: "Safety space", selectable: true, has_children: true }],
      },
    ],
    has_more: false,
    next_cursor: null,
    page_size: 50,
  },
}

function rule(
  businessMode: "fixed" | "dynamic",
  targetMode: "fixed" | "dynamic"
): DeveloperTokenFileSyncRule {
  const dynamic = businessMode === "dynamic" || targetMode === "dynamic"
  return {
    category: { code: "POLICY", subcategory_code: "MGMT_POLICY" },
    business_domain: {
      mode: businessMode,
      code: businessMode === "fixed" ? "SAFETY" : null,
    },
    target_space: {
      mode: targetMode,
      knowledge_id: targetMode === "fixed" ? 118 : null,
      folder_id: null,
    },
    dynamic_source: dynamic ? "responsible_person_id" : null,
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

  it("normalizes codes and removes fields that conflict with modes", () => {
    expect(normalizeFileSyncRule({
      category: { code: " policy ", subcategory_code: " mgmt_policy " },
      business_domain: { mode: "dynamic", code: " safety " },
      target_space: { mode: "fixed", knowledge_id: 118, folder_id: 4096 },
      dynamic_source: "department_id",
    })).toEqual({
      category: { code: "POLICY", subcategory_code: "MGMT_POLICY" },
      business_domain: { mode: "dynamic", code: null },
      target_space: { mode: "fixed", knowledge_id: 118, folder_id: 4096 },
      dynamic_source: "department_id",
    })
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
      target_space: { mode: "fixed", knowledge_id: 999, folder_id: 4096 },
    }, options, {
      knowledge_id: 999,
      knowledge_name: null,
      target_type: "folder",
      folder_id: 4096,
      folder_path: [],
      stale: true,
    })).toEqual({ field: "targetSpace", reason: "stale" })
  })

  it("validates folder ids without assuming the current space page is exhaustive", () => {
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "fixed"),
      target_space: { mode: "fixed", knowledge_id: 999, folder_id: 4096 },
    }, options)).toBeNull()
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "fixed"),
      target_space: { mode: "fixed", knowledge_id: 118, folder_id: -1 },
    }, options)).toEqual({ field: "targetSpace", reason: "invalid" })
  })

  it("uses the same 16-character business-domain code contract as the backend", () => {
    expect(findInvalidFileSyncRule({
      ...rule("fixed", "dynamic"),
      business_domain: { mode: "fixed", code: "BAD-CODE" },
    })).toEqual({ field: "businessDomain", reason: "invalid" })
  })

  it("clears incompatible fixed values and a now-unused dynamic source on mode changes", () => {
    const dynamicBusiness = changeFileSyncRuleMode(rule("fixed", "fixed"), "businessDomain", "dynamic")
    expect(dynamicBusiness.business_domain).toEqual({ mode: "dynamic", code: null })

    const fixedAgain = changeFileSyncRuleMode(
      { ...dynamicBusiness, dynamic_source: "department_id" },
      "businessDomain",
      "fixed"
    )
    expect(fixedAgain.dynamic_source).toBeNull()

    const dynamicTarget = changeFileSyncRuleMode(rule("fixed", "fixed"), "targetSpace", "dynamic")
    expect(dynamicTarget.target_space).toEqual({
      mode: "dynamic",
      knowledge_id: null,
      folder_id: null,
    })
  })

  it("formats localized configured and unconfigured summaries without option lookups", () => {
    const labels = {
      notConfigured: "Not configured",
      businessDomain: "Domain",
      targetSpace: "Space",
      dynamicDepartment: "Dynamic(department)",
      dynamicResponsiblePerson: "Dynamic(responsible person)",
    }

    expect(formatFileSyncRuleSummary(null, labels)).toBe("Not configured")
    expect(formatFileSyncRuleSummary(rule("fixed", "dynamic"), labels)).toBe(
      "POLICY/MGMT_POLICY · Domain: SAFETY · Space: Dynamic(responsible person)"
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
