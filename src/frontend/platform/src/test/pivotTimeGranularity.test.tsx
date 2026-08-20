import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useChartState } from "@/pages/Dashboard/components/config/useChartState"
import { ChartType, DashboardComponent } from "@/pages/Dashboard/types/dataConfig"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock("@/store/dashboardStore", () => ({
  useComponentEditorStore: () => ({ updateEditingComponent: vi.fn() }),
  useEditorDashboardStore: () => ({ refreshChart: vi.fn() }),
}))

describe("pivot table time granularity", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("restores the saved day granularity from the stack dimension", async () => {
    const component = {
      id: "pivot-time",
      title: "交叉表",
      type: ChartType.PivotTable,
      dataset_code: "mid_knowledge_space_content_stat",
      data_config: {
        dimensions: [],
        metrics: [],
        fieldOrder: [],
        filters: [],
        filtersLogic: "and",
        isConfigured: true,
        stackDimension: {
          fieldId: "timestamp",
          fieldName: "时间(日)",
          fieldCode: "timestamp",
          displayName: "时间(日)",
          sort: null,
          timeGranularity: "day",
        },
      },
      style_config: {},
    } as unknown as DashboardComponent

    const { result } = renderHook(() => useChartState(component))

    await waitFor(() => {
      expect(result.current.stackDimensions).toHaveLength(1)
    })
    expect(result.current.stackDimensions[0].timeGranularity).toBe("day")
  })
})
