import { describe, expect, it } from "vitest"

import { transformStackedData } from "@/controllers/API/dashboard"

const component = (metrics: { displayName: string }[]) =>
  ({ data_config: { metrics } }) as any

describe("stacked chart transform", () => {
  it("keeps one series per stack value when a single metric is configured", () => {
    const data = transformStackedData(
      {
        dimensions: [
          ["空间A", "A类"],
          ["空间A", "B类"],
          ["空间B", "A类"],
          ["空间B", "B类"],
        ],
        value: [[2], [3], [4], [5]],
      },
      component([{ displayName: "总文件数" }]),
    )

    expect(data.dimensions).toEqual(["空间A", "空间B"])
    expect(data.series.map(series => series.name)).toEqual(["A类", "B类"])
    expect(data.series.map(series => series.data)).toEqual([
      [2, 4],
      [3, 5],
    ])
    expect(data.series.every(series => series.stackGroup === undefined)).toBe(true)
  })

  it("keeps every metric and stacks each metric separately", () => {
    const data = transformStackedData(
      {
        dimensions: [
          ["空间A", "A类"],
          ["空间A", "B类"],
          ["空间B", "A类"],
          ["空间B", "B类"],
        ],
        value: [
          [2, 1],
          [3, 0],
          [4, 2],
          [5, 3],
        ],
      },
      component([{ displayName: "总文件数" }, { displayName: "新增文件数" }]),
    )

    expect(data.series.map(series => series.name)).toEqual([
      "总文件数 · A类",
      "总文件数 · B类",
      "新增文件数 · A类",
      "新增文件数 · B类",
    ])
    expect(data.series.map(series => series.stackGroup)).toEqual([
      "总文件数",
      "总文件数",
      "新增文件数",
      "新增文件数",
    ])
    // Second metric must survive; the previous transform only read value[index][0].
    expect(data.series[2].data).toEqual([1, 2])
    expect(data.series[3].data).toEqual([0, 3])
  })

  it("shows every category of a TOP-N result instead of truncating the last one", () => {
    // Backend TOP-N now truncates by category, but the shape is the same as before:
    // 5 rows may still span 3 categories when each category has a stack value.
    const data = transformStackedData(
      {
        dimensions: [
          ["空间1", "A类"],
          ["空间1", "B类"],
          ["空间2", "A类"],
          ["空间2", "B类"],
          ["空间3", "A类"],
        ],
        value: [[1, 1], [1, 1], [2, 2], [2, 2], [3, 3]],
      },
      component([{ displayName: "总文件数" }, { displayName: "新增文件数" }]),
    )

    expect(data.dimensions).toEqual(["空间1", "空间2", "空间3"])
    expect(data.series.find(series => series.name === "总文件数 · B类")?.data).toEqual([1, 2, null])
  })
})
