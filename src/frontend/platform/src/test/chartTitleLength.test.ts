import { describe, expect, it } from "vitest"
import {
  CHART_TITLE_MAX_LENGTH,
  limitChartTitleLength,
} from "../pages/Dashboard/chartTitle"

describe("dashboard chart title length", () => {
  it("keeps at most 30 characters", () => {
    const title = "图".repeat(31)

    expect(CHART_TITLE_MAX_LENGTH).toBe(30)
    expect(limitChartTitleLength(title)).toBe("图".repeat(30))
  })
})
