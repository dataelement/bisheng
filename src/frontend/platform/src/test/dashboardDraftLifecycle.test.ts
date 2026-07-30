import { beforeEach, describe, expect, it } from "vitest"

import {
  useComponentEditorStore,
  useEditorDashboardStore,
} from "@/store/dashboardStore"
import {
  ChartType,
  createDefaultDataConfig,
  Dashboard,
  DashboardComponent,
} from "@/pages/Dashboard/types/dataConfig"

const createComponent = (id: string, title: string): DashboardComponent => ({
  id,
  dashboard_id: "dashboard-1",
  title,
  type: ChartType.Bar,
  dataset_code: "dataset-1",
  data_config: createDefaultDataConfig(ChartType.Bar),
  style_config: {} as DashboardComponent["style_config"],
  create_time: "",
  update_time: "",
})

const createDashboard = (): Dashboard => ({
  id: "dashboard-1",
  title: "运营看板",
  description: "",
  status: "draft",
  dashboard_type: "custom",
  layout_config: {
    layouts: [
      { i: "chart-1", x: 0, y: 0, w: 8, h: 8 },
      { i: "chart-2", x: 8, y: 0, w: 8, h: 8 },
    ],
  },
  style_config: { theme: "light" },
  create_time: "",
  update_time: "",
  is_default: false,
  user_name: "tester",
  write: true,
  components: [
    createComponent("chart-1", "原始图表"),
    createComponent("chart-2", "第二个图表"),
  ],
})

describe("dashboard chart draft lifecycle", () => {
  beforeEach(() => {
    useEditorDashboardStore.getState().reset()
    useComponentEditorStore.setState({
      editingComponent: null,
      hasChange: false,
      draftVersion: 0,
    })
    useEditorDashboardStore.getState().setCurrentDashboard(createDashboard())
  })

  it("keeps form edits isolated until Update Chart Data is applied", () => {
    const componentEditor = useComponentEditorStore.getState()
    componentEditor.copyFromDashboard("chart-1")
    componentEditor.updateEditingComponent({ title: "仅表单草稿" })

    expect(
      useEditorDashboardStore
        .getState()
        .currentDashboard?.components.find(component => component.id === "chart-1")
        ?.title
    ).toBe("原始图表")
    expect(useEditorDashboardStore.getState().hasUnsavedChanges).toBe(false)

    componentEditor.applyEditingComponent()

    expect(
      useEditorDashboardStore
        .getState()
        .currentDashboard?.components.find(component => component.id === "chart-1")
        ?.title
    ).toBe("仅表单草稿")
    expect(useEditorDashboardStore.getState().hasUnsavedChanges).toBe(true)
  })

  it("restores an applied preview to the last saved component", () => {
    const componentEditor = useComponentEditorStore.getState()
    componentEditor.copyFromDashboard("chart-1")
    componentEditor.applyEditingComponent({ title: "临时预览" })
    componentEditor.cancelEditingComponent()

    expect(
      useEditorDashboardStore
        .getState()
        .currentDashboard?.components.find(component => component.id === "chart-1")
        ?.title
    ).toBe("原始图表")
    expect(useComponentEditorStore.getState().editingComponent?.title).toBe("原始图表")
    expect(useEditorDashboardStore.getState().hasUnsavedChanges).toBe(false)
  })

  it("uses the latest manual save as the next cancel baseline", () => {
    const componentEditor = useComponentEditorStore.getState()
    componentEditor.copyFromDashboard("chart-1")
    componentEditor.applyEditingComponent({ title: "第一次预览" })

    const dashboardStore = useEditorDashboardStore.getState()
    dashboardStore.markDashboardSaved({
      ...dashboardStore.currentDashboard!,
      layout_config: { layouts: dashboardStore.layouts },
    })

    componentEditor.applyEditingComponent({ title: "第二次预览" })
    componentEditor.cancelEditingComponent()

    expect(
      useEditorDashboardStore
        .getState()
        .currentDashboard?.components.find(component => component.id === "chart-1")
        ?.title
    ).toBe("第一次预览")
    expect(useEditorDashboardStore.getState().hasUnsavedChanges).toBe(false)
  })

  it("discards unapplied form changes when selecting another chart", () => {
    const componentEditor = useComponentEditorStore.getState()
    componentEditor.copyFromDashboard("chart-1")
    componentEditor.updateEditingComponent({ title: "不应泄漏" })
    componentEditor.copyFromDashboard("chart-2")

    expect(
      useEditorDashboardStore
        .getState()
        .currentDashboard?.components.find(component => component.id === "chart-1")
        ?.title
    ).toBe("原始图表")
    expect(useComponentEditorStore.getState().editingComponent?.id).toBe("chart-2")
    expect(useEditorDashboardStore.getState().hasUnsavedChanges).toBe(false)
  })
})
