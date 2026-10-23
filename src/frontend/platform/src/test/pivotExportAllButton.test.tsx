import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ComponentWrapper } from "@/pages/Dashboard/components/editor/ComponentWrapper"
import { ChartType, DashboardComponent } from "@/pages/Dashboard/types/dataConfig"

const exports = vi.hoisted(() => ({ exportAll: vi.fn(), canExport: true, isExportingAll: false }))
vi.mock("@/pages/Dashboard/components/export/useComponentExport", () => ({
  useComponentExport: () => exports,
}))
vi.mock("@/pages/Dashboard/components/charts/ChartContainer", () => ({ ChartContainer: () => null }))

const component = {
  id: "c1", dashboard_id: "d1", title: "交叉表", type: ChartType.PivotTable,
  data_config: {}, style_config: {},
} as DashboardComponent

const table = (isPreviewMode: boolean) => <ComponentWrapper
  component={component} dashboards={[]} isDark={false} isPreviewMode={isPreviewMode}
  onCopyTo={vi.fn()} onDelete={vi.fn()} onDuplicate={vi.fn()}
/>

describe("pivot export-all button", () => {
  beforeEach(() => { vi.clearAllMocks(); exports.canExport = true; exports.isExportingAll = false })

  it.each([true, false])("offers a visible one-click detail export with preview=%s", isPreviewMode => {
    render(table(isPreviewMode))
    const button = screen.getByRole("button", { name: "componentExport.exportAllDetails" })
    expect(button).not.toHaveClass("opacity-0")
    fireEvent.click(button)
    expect(exports.exportAll).toHaveBeenCalledTimes(1)
  })

  it("disables export for an unsaved table and while exporting", () => {
    exports.canExport = false
    const { rerender } = render(table(true))
    expect(screen.getByRole("button", { name: "componentExport.exportAllDetails" })).toBeDisabled()
    exports.canExport = true
    exports.isExportingAll = true
    rerender(table(true))
    expect(screen.getByRole("button", { name: "componentExport.exportAllDetails" })).toBeDisabled()
  })
})
