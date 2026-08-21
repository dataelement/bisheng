import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { PivotTable } from "@/pages/Dashboard/components/charts/PivotTable"
import { PivotTableDataResponse } from "@/pages/Dashboard/types/chartData"
import { DataConfig } from "@/pages/Dashboard/types/dataConfig"

describe("pivot table sequence column", () => {
  it("renders a one-based sequence before row dimensions", () => {
    const data: PivotTableDataResponse = {
      rowHeaders: ["上传人名称", "上传人部门名称"],
      columnHeader: "时间(日)",
      metricName: "新增文件数",
      columns: ["2026-08-06"],
      originalColumns: ["2026-08-06"],
      rows: [
        { key: ["俞宇成", "信息部"], values: [1], total: 1 },
        { key: ["张杰", "采购部"], values: [3], total: 3 },
      ],
      columnTotals: [4],
      grandTotal: 4,
    }
    const dataConfig = {
      metrics: [],
    } as DataConfig

    render(<PivotTable data={data} dataConfig={dataConfig} isDark={false} />)

    const rows = within(screen.getByRole("table")).getAllByRole("row")
    expect(within(rows[0]).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual([
      "序号",
      "上传人名称",
      "上传人部门名称",
      "2026-08-06",
      "合计",
    ])
    expect(within(rows[1]).getAllByRole("rowheader")[0]).toHaveTextContent("1")
    expect(within(rows[2]).getAllByRole("rowheader")[0]).toHaveTextContent("2")
    expect(within(rows[3]).getByText("合计")).toHaveAttribute("colspan", "3")
  })
})
