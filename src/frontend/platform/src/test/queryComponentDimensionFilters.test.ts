import { beforeEach, describe, expect, it } from "vitest"

import { useEditorDashboardStore } from "@/store/dashboardStore"
import {
  ChartType,
  createDefaultDataConfig,
  Dashboard,
  DashboardComponent,
  QueryConfig,
} from "@/pages/Dashboard/types/dataConfig"

// Customer feedback (2026-09-01): the Query component (查询组件) must support querying by
// 知识库大类/知识分类/组织架构/业务域, not just time — reusing the same {fieldId, values}
// shape the separate DimensionFilter component already sends into chartRefreshTriggers.

const chart: DashboardComponent = {
  id: "chart-1",
  dashboard_id: "dashboard-1",
  title: "图表",
  type: ChartType.Bar,
  dataset_code: "mid_knowledge_space_content_stat",
  data_config: createDefaultDataConfig(ChartType.Bar),
  style_config: {} as DashboardComponent["style_config"],
  create_time: "",
  update_time: "",
}

const queryComponent: DashboardComponent = {
  id: "query-1",
  dashboard_id: "dashboard-1",
  title: "查询组件",
  type: ChartType.Query,
  dataset_code: "",
  data_config: {
    linkedComponentIds: ["chart-1"],
    queryConditions: {
      id: "q1",
      displayType: "range",
      timeGranularity: "year_month_day",
      hasDefaultValue: false,
      defaultValue: { type: "all" as const },
    },
    dimensionFields: [
      {
        id: "space_level_name-1",
        fieldId: "space_level_name",
        fieldName: "space_level_name",
        displayName: "知识库大类",
        datasetCode: "mid_knowledge_space_content_stat",
      },
    ],
  } satisfies QueryConfig,
  style_config: {} as DashboardComponent["style_config"],
  create_time: "",
  update_time: "",
}

const createDashboard = (): Dashboard => ({
  id: "dashboard-1",
  title: "看板",
  description: "",
  status: "draft",
  dashboard_type: "custom",
  layout_config: { layouts: [] },
  style_config: { theme: "light" },
  create_time: "",
  update_time: "",
  is_default: false,
  user_name: "tester",
  write: true,
  components: [chart, queryComponent],
})

describe("Query component dimension conditions flow into chartRefreshTriggers", () => {
  beforeEach(() => {
    useEditorDashboardStore.getState().reset()
    useEditorDashboardStore.getState().setCurrentDashboard(createDashboard())
  })

  it("pushes the selected dimension values as {fieldId, values} for linked charts", () => {
    useEditorDashboardStore.getState().refreshChartsByQuery(
      queryComponent,
      undefined,
      { space_level_name: ["公共库", "部门库"] },
    )

    const triggerInfo = useEditorDashboardStore.getState().chartRefreshTriggers["chart-1"]
    expect(triggerInfo.trigger).toBe(1)
    const dimensionFilters = triggerInfo.queryParams.flatMap((param: any) => param.dimensionFilters || [])
    expect(dimensionFilters).toEqual([{ fieldId: "space_level_name", values: ["公共库", "部门库"] }])
  })

  it("omits a dimension condition entirely when nothing is selected for it", () => {
    useEditorDashboardStore.getState().refreshChartsByQuery(queryComponent, undefined, {})

    const triggerInfo = useEditorDashboardStore.getState().chartRefreshTriggers["chart-1"]
    const dimensionFilters = triggerInfo.queryParams.flatMap((param: any) => param.dimensionFilters || [])
    expect(dimensionFilters).toEqual([])
  })
})
