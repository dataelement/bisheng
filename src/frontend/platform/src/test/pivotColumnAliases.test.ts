import { resolvePivotColumnLabels } from "@/pages/Dashboard/components/charts/pivotColumnAliases"
import { describe, expect, it } from "vitest"

const stackDimension = {
  fieldId: "space_department_name",
  fieldName: "所属部门",
  fieldCode: "space_department_name",
  displayName: "所属部门",
  sort: null,
  timeGranularity: null,
}

describe("resolvePivotColumnLabels", () => {
  it("uses configured aliases for the active pivot column dimension", () => {
    expect(resolvePivotColumnLabels({
      columns: ["首钢股份钢铁板块生产部", "质量部"],
      stackDimension,
      aliasConfig: {
        fieldId: "space_department_name",
        aliases: {
          "首钢股份钢铁板块生产部": "生产部",
        },
      },
    })).toEqual(["生产部", "质量部"])
  })

  it("ignores aliases that belong to another dimension", () => {
    expect(resolvePivotColumnLabels({
      columns: ["首钢股份钢铁板块生产部"],
      stackDimension,
      aliasConfig: {
        fieldId: "primary_department_name",
        aliases: {
          "首钢股份钢铁板块生产部": "生产部",
        },
      },
    })).toEqual(["首钢股份钢铁板块生产部"])
  })
})
