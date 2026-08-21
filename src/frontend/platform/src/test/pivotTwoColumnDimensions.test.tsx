import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { transformPivotData } from "@/controllers/API/dashboard"
import { PivotTable } from "@/pages/Dashboard/components/charts/PivotTable"
import { useChartState } from "@/pages/Dashboard/components/config/useChartState"
import { ChartType, DashboardComponent, DataConfig } from "@/pages/Dashboard/types/dataConfig"

const { toastMock } = vi.hoisted(() => ({
  toastMock: vi.fn(),
}))

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ toast: toastMock }),
}))

vi.mock("@/store/dashboardStore", () => ({
  useComponentEditorStore: () => ({ updateEditingComponent: vi.fn() }),
  useEditorDashboardStore: () => ({ refreshChart: vi.fn() }),
}))

const stackDimensions = [
  {
    fieldId: "timestamp",
    fieldName: "时间(日)",
    fieldCode: "timestamp",
    displayName: "时间(日)",
    sort: null,
    timeGranularity: "day",
  },
  {
    fieldId: "category_name",
    fieldName: "知识分类",
    fieldCode: "category_name",
    displayName: "知识分类",
    sort: null,
    timeGranularity: null,
  },
]

const component = {
  id: "pivot-two-columns",
  title: "交叉表",
  type: ChartType.PivotTable,
  dataset_code: "mid_knowledge_space_content_stat",
  data_config: {
    dimensions: [
      {
        fieldId: "uploader_name",
        fieldName: "上传人名称",
        fieldCode: "uploader_name",
        displayName: "上传人名称",
        sort: null,
        timeGranularity: null,
      },
      {
        fieldId: "department_name",
        fieldName: "上传人部门名称",
        fieldCode: "department_name",
        displayName: "上传人部门名称",
        sort: null,
        timeGranularity: null,
      },
    ],
    stackDimension: stackDimensions[0],
    stackDimensions,
    metrics: [
      {
        fieldId: "new_file_count",
        fieldName: "新增文件数",
        fieldCode: "new_file_count",
        displayName: "新增文件数",
        aggregation: "sum",
        isVirtual: false,
        sort: null,
        numberFormat: {
          type: "number",
          decimalPlaces: 0,
          thousandSeparator: true,
        },
      },
    ],
    fieldOrder: [],
    filters: [],
    filtersLogic: "and",
    resultLimit: { limitType: "all" },
    isConfigured: true,
  },
  style_config: {},
} as unknown as DashboardComponent

describe("pivot table two column dimensions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("restores, saves, and limits pivot column dimensions to two", async () => {
    const { result } = renderHook(() => useChartState(component))

    await waitFor(() => {
      expect(result.current.stackDimensions).toHaveLength(2)
    })
    expect(result.current.stackDimensions.map(item => item.fieldId)).toEqual([
      "timestamp",
      "category_name",
    ])
    expect(result.current.stackDimensions[0].timeGranularity).toBe("day")

    const savedConfig = result.current.getDataConfig("all", "")
    expect(savedConfig.stackDimensions?.map(item => item.fieldId)).toEqual([
      "timestamp",
      "category_name",
    ])
    expect(savedConfig.stackDimension?.fieldId).toBe("timestamp")

    const dropEvent = {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      dataTransfer: {
        getData: () => JSON.stringify({
          id: "business_domain_name",
          name: "business_domain_name",
          displayName: "业务域",
          fieldType: "dimension",
        }),
      },
    } as unknown as React.DragEvent

    act(() => {
      result.current.handleDrop(dropEvent, "stack", true)
    })

    expect(result.current.stackDimensions).toHaveLength(2)
    expect(toastMock).toHaveBeenCalled()
  })

  it("pivots complete column paths, accumulates duplicates, and renders grouped headers", () => {
    const data = transformPivotData(
      {
        dimensions: [
          ["张三", "信息部", "2026-08-20", "政策制度"],
          ["张三", "信息部", "2026-08-20", "政策制度"],
          ["张三", "信息部", "2026-08-20", "标准规范"],
          ["李四", "采购部", "2026-08-21", "政策制度"],
        ],
        value: [[1], [2], [4], [5]],
      },
      component,
    )

    expect(data.columnHeaders).toEqual(["时间(日)", "知识分类"])
    expect(data.columnPaths).toEqual([
      ["2026-08-20", "政策制度"],
      ["2026-08-20", "标准规范"],
      ["2026-08-21", "政策制度"],
    ])
    expect(data.rows[0]).toEqual({
      key: ["张三", "信息部"],
      values: [3, 4, 0],
      total: 7,
    })
    expect(data.columnTotals).toEqual([3, 4, 5])
    expect(data.grandTotal).toBe(12)

    render(
      <PivotTable
        data={data}
        dataConfig={component.data_config as DataConfig}
        isDark={false}
      />,
    )

    const headerRows = within(screen.getByRole("table")).getAllByRole("row").slice(0, 2)
    const firstHeaderCells = within(headerRows[0]).getAllByRole("columnheader")
    expect(firstHeaderCells.map(cell => cell.textContent)).toEqual([
      "序号",
      "上传人名称",
      "上传人部门名称",
      "2026-08-20",
      "2026-08-21",
      "合计",
    ])
    expect(firstHeaderCells[3]).toHaveAttribute("colspan", "2")
    expect(firstHeaderCells[4]).toHaveAttribute("colspan", "1")
    expect(within(headerRows[1]).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual([
      "政策制度",
      "标准规范",
      "政策制度",
    ])
  })

  it("keeps a legacy single column dimension as a single header row", () => {
    const legacyComponent = {
      ...component,
      data_config: {
        ...component.data_config,
        stackDimensions: undefined,
        stackDimension: stackDimensions[1],
      },
    } as DashboardComponent
    const data = transformPivotData(
      {
        dimensions: [["张三", "信息部", "政策制度"]],
        value: [[2]],
      },
      legacyComponent,
    )

    expect(data.columnHeaders).toEqual(["知识分类"])
    expect(data.columnPaths).toEqual([["政策制度"]])

    render(
      <PivotTable
        data={data}
        dataConfig={legacyComponent.data_config as DataConfig}
        isDark={false}
      />,
    )

    const rows = within(screen.getByRole("table")).getAllByRole("row")
    expect(within(rows[0]).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual([
      "序号",
      "上传人名称",
      "上传人部门名称",
      "政策制度",
      "合计",
    ])
  })
})
