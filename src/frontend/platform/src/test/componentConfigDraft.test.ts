import { describe, expect, it } from "vitest"
import {
  resolveAppliedComponentTitle,
  resolveStyleConfigDefaults,
} from "../pages/Dashboard/components/config/componentConfigDraft"
import type { ComponentStyleConfig } from "../pages/Dashboard/types/dataConfig"

const defaultStyleConfig = {
  showDataLabel: false,
} as ComponentStyleConfig

describe("resolveAppliedComponentTitle", () => {
  it("keeps the title entered in the style panel for a metric card", () => {
    expect(resolveAppliedComponentTitle({
      styleTitle: "知识内化量",
      componentTitle: "总文件数",
      metricFieldName: "总文件数",
    })).toBe("知识内化量")
  })

  it("keeps the title entered in the style panel for other chart types", () => {
    expect(resolveAppliedComponentTitle({
      styleTitle: "部门知识贡献",
      componentTitle: "旧图表标题",
      metricFieldName: "总文件数",
    })).toBe("部门知识贡献")
  })

  it("uses the component title and then the metric name only as fallbacks", () => {
    expect(resolveAppliedComponentTitle({
      styleTitle: "",
      componentTitle: "已有标题",
      metricFieldName: "总文件数",
    })).toBe("已有标题")

    expect(resolveAppliedComponentTitle({
      styleTitle: " ",
      componentTitle: "",
      metricFieldName: "总文件数",
    })).toBe("总文件数")
  })
})

describe("resolveStyleConfigDefaults", () => {
  it.each(["pie", "donut"])(
    "enables data labels by default for %s charts",
    (chartType) => {
      expect(resolveStyleConfigDefaults({
        chartType,
        defaultConfig: defaultStyleConfig,
      }).showDataLabel).toBe(true)
    },
  )

  it("keeps data labels disabled by default for other chart types", () => {
    expect(resolveStyleConfigDefaults({
      chartType: "bar",
      defaultConfig: defaultStyleConfig,
    }).showDataLabel).toBe(false)
  })

  it("respects an explicit user choice to hide circular chart labels", () => {
    expect(resolveStyleConfigDefaults({
      chartType: "donut",
      defaultConfig: defaultStyleConfig,
      componentConfig: { showDataLabel: false },
    }).showDataLabel).toBe(false)
  })
})
