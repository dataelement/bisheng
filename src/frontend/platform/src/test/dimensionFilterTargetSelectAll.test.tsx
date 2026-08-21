import { DimensionFilterConfigurator } from "@/pages/Dashboard/components/config/DimensionFilterConfigurator"
import {
  ChartType,
  DashboardComponent,
  DimensionFilterConfig,
} from "@/pages/Dashboard/types/dataConfig"
import { fireEvent, render, screen } from "@/test/test-utils"
import { describe, expect, it, vi } from "vitest"

const targetCharts = [
  {
    id: "chart-1",
    title: "知识统计",
    type: ChartType.Bar,
    dataset_code: "mid_knowledge_space_content_stat",
  },
  {
    id: "chart-2",
    title: "知识组织化总量",
    type: ChartType.Metric,
    dataset_code: "mid_knowledge_space_content_stat",
  },
]

vi.mock("react-query", () => ({
  useQuery: () => ({
    data: [
      {
        dataset_code: "mid_knowledge_space_content_stat",
        dataset_name: "知识空间内容统计",
        schema_config: {
          dimensions: [
            { field: "space_level", name: "知识库大类编码" },
          ],
        },
      },
    ],
  }),
}))

vi.mock("@/store/dashboardStore", () => ({
  useEditorDashboardStore: (selector: (state: any) => unknown) => selector({
    currentDashboard: { components: targetCharts },
  }),
}))

const component = {
  id: "dimension-filter-1",
  dashboard_id: "dashboard-1",
  title: "维度筛选",
  type: ChartType.DimensionFilter,
  dataset_code: "mid_knowledge_space_content_stat",
  data_config: {
    fields: [
      {
        id: "space-level",
        fieldId: "space_level",
        fieldName: "知识库大类编码",
        displayName: "知识库大类编码",
        defaultValues: [],
      },
    ],
    linkedComponentIds: [],
  } satisfies DimensionFilterConfig,
  style_config: {},
  create_time: "",
  update_time: "",
} as DashboardComponent

describe("dimension filter target chart select all", () => {
  it("selects and clears every target chart and saves the selected ids", () => {
    const onSave = vi.fn()
    render(
      <DimensionFilterConfigurator
        component={component}
        onSave={onSave}
        onCancel={vi.fn()}
      />
    )

    const selectAll = screen.getByRole("checkbox", { name: "全选" })
    const firstChart = screen.getByRole("checkbox", { name: "知识统计" })
    const secondChart = screen.getByRole("checkbox", { name: "知识组织化总量" })

    fireEvent.click(selectAll)
    expect(selectAll).toBeChecked()
    expect(firstChart).toBeChecked()
    expect(secondChart).toBeChecked()

    fireEvent.click(firstChart)
    expect(selectAll).not.toBeChecked()
    expect(firstChart).not.toBeChecked()
    expect(secondChart).toBeChecked()

    fireEvent.click(selectAll)
    fireEvent.click(screen.getByRole("button", { name: "更新筛选预览" }))
    expect(onSave).toHaveBeenCalledWith(
      "mid_knowledge_space_content_stat",
      expect.objectContaining({ linkedComponentIds: ["chart-1", "chart-2"] })
    )

    fireEvent.click(selectAll)
    expect(firstChart).not.toBeChecked()
    expect(secondChart).not.toBeChecked()
  })
})
