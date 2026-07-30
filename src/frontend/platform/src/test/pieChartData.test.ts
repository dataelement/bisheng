import { describe, expect, it } from "vitest"
import { applyPieResultLimit } from "../pages/Dashboard/components/charts/pieChartData"

const DATA = [
  { name: "流程与程序", value: 30 },
  { name: "标准规范", value: 25 },
  { name: "政策制度", value: 20 },
  { name: "技术规程与诀窍", value: 15 },
]

describe("applyPieResultLimit", () => {
  it("keeps all data when the result limit is all", () => {
    expect(applyPieResultLimit(DATA, { limitType: "all" })).toEqual(DATA)
  })

  it("keeps only the first X data items", () => {
    expect(applyPieResultLimit(DATA, { limitType: "limited", limit: 2 })).toEqual(DATA.slice(0, 2))
  })

  it("groups all remaining data into Other", () => {
    expect(
      applyPieResultLimit(DATA, { limitType: "limited_with_other", limit: 2 }, "其他"),
    ).toEqual([
      { name: "流程与程序", value: 30 },
      { name: "标准规范", value: 25 },
      { name: "其他", value: 35 },
    ])
  })

  it("does not append an empty Other item", () => {
    expect(
      applyPieResultLimit(DATA, { limitType: "limited_with_other", limit: 10 }, "其他"),
    ).toEqual(DATA)
  })
})
