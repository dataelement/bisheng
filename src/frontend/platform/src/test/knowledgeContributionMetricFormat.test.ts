import { describe, expect, it } from "vitest"
import { createMetricDatasetField } from "../pages/Dashboard/components/config/DatasetSelector"
import { resolveMetricNumberFormat } from "../pages/Dashboard/components/config/useChartState"

describe("knowledge contribution metric format", () => {
  it("uses the dataset percent default", () => {
    const field = createMetricDatasetField(
      {
        field: "knowledge_contribution_ratio",
        field_type: "number",
        name: "知识贡献占比",
        is_virtual: true,
        calculation: "share_of_total",
        default_number_format: {
          type: "percent",
          decimalPlaces: 1,
          thousandSeparator: false,
        },
      },
      "知识贡献占比",
    )

    expect(
      resolveMetricNumberFormat({
        fieldId: field.fieldId,
        numberFormat: field.numberFormat,
      }),
    ).toEqual({
      type: "percent",
      decimalPlaces: 1,
      thousandSeparator: false,
    })
  })

  it("keeps the existing divide metric default", () => {
    expect(resolveMetricNumberFormat({ isDivide: "divide" })).toEqual({
      type: "percent",
      decimalPlaces: 2,
      unit: undefined,
      suffix: "",
      thousandSeparator: false,
    })
  })

  it("preserves a saved component-level format", () => {
    const savedFormat = {
      type: "number" as const,
      decimalPlaces: 3,
      unit: "K",
      suffix: "份",
      thousandSeparator: true,
    }

    expect(
      resolveMetricNumberFormat({
        isDivide: undefined,
        numberFormat: savedFormat,
      }),
    ).toEqual(savedFormat)
  })
})
