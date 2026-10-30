import { describe, expect, it } from "vitest"

import { transformPivotData } from "@/controllers/API/dashboard"
import { unitConversion } from "@/pages/Dashboard/components/charts/MetricCard"
import { DashboardComponent } from "@/pages/Dashboard/types/dataConfig"
import { reconcileShareRatios, type ShareTable } from "@/pages/Dashboard/utils/controlledRounding"

const PLACES = 1
const SCALE = 1000

function units(ratio: number): number {
  return Math.round(ratio * SCALE)
}

function displayed(ratio: number): number {
  return Number(unitConversion(ratio, {
    metrics: [{ numberFormat: { type: "percent", decimalPlaces: PLACES, thousandSeparator: false } }],
  })[0])
}

function expectAdditive(table: ShareTable) {
  const reconciled = reconcileShareRatios(table, PLACES)
  expect(reconciled).not.toBeNull()
  const result = reconciled!
  const cellUnits = result.cells.map(row => row.map(units))
  cellUnits.forEach((row, rowIndex) => {
    expect(row.reduce((total, value) => total + value, 0)).toBe(units(result.rowTotals[rowIndex]))
    row.forEach((value, columnIndex) => {
      const exact = table.cells[rowIndex][columnIndex] * SCALE
      if (exact === 0) {
        expect(value).toBe(0)
      } else {
        expect(value).toBeGreaterThanOrEqual(Math.floor(exact - 1e-6))
        expect(value).toBeLessThanOrEqual(Math.ceil(exact + 1e-6))
      }
    })
  })
  result.columnTotals.forEach((total, columnIndex) => {
    const columnSum = cellUnits.reduce((totalUnits, row) => totalUnits + row[columnIndex], 0)
    expect(columnSum).toBe(units(total))
  })
  expect(result.rowTotals.reduce((total, value) => units(value) + total, 0)).toBe(units(result.grandTotal))
  expect(result.columnTotals.reduce((total, value) => units(value) + total, 0)).toBe(units(result.grandTotal))
  const shownColumnSums = result.columnTotals.map((_, columnIndex) =>
    result.cells.reduce((total, row) => total + displayed(row[columnIndex]), 0))
  expect(shownColumnSums.map(value => value.toFixed(1))).toEqual(result.columnTotals.map(value => displayed(value).toFixed(1)))
}

describe("知识贡献占比显示配平", () => {
  it("把各自四舍五入后对不上的一列配成列合计", () => {
    const total = 10000
    const count = 14
    const cell = count / total
    const column = (count * 5) / total
    expectAdditive({
      cells: [[cell], [cell], [cell], [cell], [cell]],
      rowTotals: [cell, cell, cell, cell, cell],
      columnTotals: [column],
      grandTotal: column,
    })
    const reconciled = reconcileShareRatios({
      cells: [[cell], [cell], [cell], [cell], [cell]],
      rowTotals: [cell, cell, cell, cell, cell],
      columnTotals: [column],
      grandTotal: column,
    }, PLACES)!
    expect(displayed(reconciled.grandTotal)).toBe(0.7)
    // 1.4 tenths floors to 1. Five cells sum to 7 tenths, so two cells receive the extra 0.1%.
    expect(reconciled.cells.map(row => displayed(row[0])).sort()).toEqual([0.1, 0.1, 0.1, 0.2, 0.2])
  })

  it("真实为 0 的格子保持为 0", () => {
    const reconciled = reconcileShareRatios({
      cells: [[0.006, 0], [0, 0.004]],
      rowTotals: [0.006, 0.004],
      columnTotals: [0.006, 0.004],
      grandTotal: 0.01,
    }, PLACES)!
    expect(reconciled.cells[0][1]).toBe(0)
    expect(reconciled.cells[1][0]).toBe(0)
    expectAdditive({
      cells: [[0.006, 0], [0, 0.004]],
      rowTotals: [0.006, 0.004],
      columnTotals: [0.006, 0.004],
      grandTotal: 0.01,
    })
  })

  it("随机份数表的行、列和总计都能对上", () => {
    let seed = 17
    const next = () => {
      seed = (seed * 1103515245 + 12345) % 2147483647
      return seed
    }
    for (let sample = 0; sample < 30; sample++) {
      const rows = 2 + (next() % 6)
      const columns = 2 + (next() % 6)
      const counts = Array.from({ length: rows }, () =>
        Array.from({ length: columns }, () => next() % 40))
      const total = counts.flat().reduce((sum, value) => sum + value, 0) || 1
      const rowTotals = counts.map(row => row.reduce((sum, value) => sum + value, 0) / total)
      const columnTotals = counts[0].map((_, column) => counts.reduce((sum, row) => sum + row[column], 0) / total)
      expectAdditive({
        cells: counts.map(row => row.map(value => value / total)),
        rowTotals,
        columnTotals,
        grandTotal: 1,
      })
    }
  })
})

function rollup(indexes: number[], rows: [unknown[], number][]) {
  return { metric_index: 0, dimension_indexes: indexes, rows: rows.map(([dimensions, value]) => ({ dimensions, value })) }
}

describe("知识贡献占比交叉表", () => {
  it("展示值按 0.1 个百分点相加等于合计", () => {
    const total = 10000
    const count = 14
    const cell = count / total
    const column = (count * 5) / total
    const levels = ["个人库", "公共库", "团队库", "科室库", "部门库"]
    const component = {
      data_config: {
        dimensions: [{ fieldId: "space_level_name", displayName: "类型" }],
        stackDimensions: [{ fieldId: "business_domain_name", displayName: "业务域" }],
        metrics: [{
          fieldId: "knowledge_contribution_ratio",
          displayName: "知识贡献占比",
          numberFormat: { type: "percent", decimalPlaces: 1, thousandSeparator: false },
        }],
      },
    } as DashboardComponent
    const result = transformPivotData({
      dimensions: levels.map(level => [level, "营销"]),
      value: levels.map(() => [cell]),
      rollups: [
        rollup([], [[[], column]]),
        rollup([0], levels.map(level => [[level], cell])),
        rollup([1], [[["营销"], column]]),
        rollup([0, 1], levels.map(level => [[level, "营销"], cell])),
      ],
    }, component)
    const format = component.data_config.metrics[0]
    const shown = (value: number) => Number(unitConversion(value, { metrics: [format] })[0])
    const columnSum = result.rows.reduce((totalShown, row) => totalShown + shown(row.values[0]), 0)
    expect(columnSum).toBeCloseTo(shown(result.columnTotals[0]), 5)
    expect(shown(result.grandTotal)).toBe(0.7)
    expect(result.rows.map(row => shown(row.total)).reduce((totalShown, value) => totalShown + value, 0)).toBeCloseTo(0.7, 5)
  })
})
