import { describe, expect, it } from "vitest"
import { sumMetricValues } from "../pages/Dashboard/components/charts/metricCardValue"

describe("sumMetricValues", () => {
  it("adds all configured metric values from the same query row", () => {
    expect(sumMetricValues([12, 8])).toBe(20)
  })

  it("accepts numeric response strings and ignores missing or invalid values", () => {
    expect(sumMetricValues(["12", null, undefined, "invalid", 8])).toBe(20)
  })

  it("returns zero when the query has no metric row", () => {
    expect(sumMetricValues(undefined)).toBe(0)
    expect(sumMetricValues([])).toBe(0)
  })
})
