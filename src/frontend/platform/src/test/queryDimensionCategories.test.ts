import { describe, expect, it } from "vitest"

import { queryDimensionCategoryForField } from "@/pages/Dashboard/utils/queryDimensionCategories"

// Customer feedback (2026-09-01): the Query component's dimension-condition picker
// (ChartSelector.tsx) only offers fields belonging to these 4 categories.
describe("queryDimensionCategoryForField", () => {
  it("categorizes 知识库大类", () => {
    expect(queryDimensionCategoryForField("space_level_name")).toBe("space_level")
  })

  it("categorizes 知识分类 (both levels)", () => {
    expect(queryDimensionCategoryForField("file_category_name")).toBe("file_category")
    expect(queryDimensionCategoryForField("file_subcategory_name")).toBe("file_category")
  })

  it("categorizes 业务域", () => {
    expect(queryDimensionCategoryForField("business_domain_name")).toBe("business_domain")
  })

  it("categorizes org-hierarchy fields (both belonging_* and uploader_*) as 组织架构", () => {
    expect(queryDimensionCategoryForField("belonging_department_name")).toBe("org_hierarchy")
    expect(queryDimensionCategoryForField("uploader_office_name")).toBe("org_hierarchy")
  })

  it("returns null for fields outside the 4 categories (e.g. code fields, unrelated dimensions)", () => {
    expect(queryDimensionCategoryForField("space_level")).toBeNull()
    expect(queryDimensionCategoryForField("file_category_code")).toBeNull()
    expect(queryDimensionCategoryForField("app_type")).toBeNull()
  })
})
