import { ComponentWrapper } from "@/pages/Dashboard/components/editor/ComponentWrapper"
import {
  ChartType,
  DashboardComponent,
} from "@/pages/Dashboard/types/dataConfig"
import { fireEvent, render, screen } from "@/test/test-utils"
import { describe, expect, it, vi } from "vitest"

vi.mock("@/pages/Dashboard/components/charts/ChartContainer", () => ({
  ChartContainer: () => null,
}))

const component: DashboardComponent = {
  id: "chart-1",
  dashboard_id: "dashboard-1",
  title: "图表标题",
  type: ChartType.Bar,
  dataset_code: "dataset-1",
  data_config: {
    dimensions: [],
    metrics: [],
    fieldOrder: [],
    filters: [],
    resultLimit: { limitType: "all" },
    isConfigured: false,
  },
  style_config: {},
  create_time: "",
  update_time: "",
}

describe("dashboard chart title input", () => {
  it("limits direct chart renaming to 30 characters", () => {
    render(
      <ComponentWrapper
        component={component}
        dashboards={[]}
        isDark={false}
        isPreviewMode={false}
        onCopyTo={vi.fn()}
        onDelete={vi.fn()}
        onDuplicate={vi.fn()}
      />,
    )

    fireEvent.doubleClick(screen.getByText("图表标题"))
    const input = screen.getByDisplayValue("图表标题")
    expect(input).toHaveAttribute("maxlength", "30")

    fireEvent.change(input, { target: { value: "图".repeat(31) } })
    expect(input).toHaveValue("图".repeat(30))
  })
})
