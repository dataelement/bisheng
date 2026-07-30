import type { ComponentStyleConfig } from "../../types/dataConfig"

interface ResolveAppliedComponentTitleOptions {
  styleTitle?: string
  componentTitle?: string
  metricFieldName?: string
}

type ResolveStyleConfigDefaultsOptions = {
  chartType?: string
  defaultConfig: ComponentStyleConfig
  componentConfig?: Partial<ComponentStyleConfig>
}

export function resolveStyleConfigDefaults({
  chartType,
  defaultConfig,
  componentConfig = {},
}: ResolveStyleConfigDefaultsOptions): ComponentStyleConfig {
  const isCircularChart = chartType === "pie" || chartType === "donut"

  return {
    ...defaultConfig,
    ...(isCircularChart ? { showDataLabel: true } : {}),
    ...componentConfig,
  }
}

export function resolveAppliedComponentTitle({
  styleTitle,
  componentTitle,
  metricFieldName,
}: ResolveAppliedComponentTitleOptions) {
  return [styleTitle, componentTitle, metricFieldName]
    .find(value => typeof value === "string" && value.trim().length > 0)
    ?.trim() ?? ""
}
