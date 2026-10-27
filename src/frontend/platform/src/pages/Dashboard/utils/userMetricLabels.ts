import type { DashboardComponent } from "../types/dataConfig"

const USER_METRIC_LABELS: Record<string, { name: string; legacy: string[] }> = {
  logged_in_employee_count: { name: "累积登录人数", legacy: ["实际登录人数", "累计实际登录人数"] },
  active_employee_count: { name: "全员有效用户数", legacy: ["全员总数", "有效人员总数"] },
  participation_rate: { name: "全员参与度占比", legacy: ["全员参与占比"] },
}
const USER_DATASETS = new Set(["mid_user_increment", "mid_user_daily_participation"])

function renameDefault(label: string, fieldId: string): string {
  const metric = USER_METRIC_LABELS[fieldId]
  return metric?.legacy.includes(label) ? metric.name : label
}

function renameField<T extends { fieldId: string }>(field: T): T {
  if (!USER_METRIC_LABELS[field.fieldId]) return field
  return {
    ...field,
    ...("fieldName" in field && typeof field.fieldName === "string"
      ? { fieldName: renameDefault(field.fieldName, field.fieldId) } : {}),
    ...("displayName" in field && typeof field.displayName === "string"
      ? { displayName: renameDefault(field.displayName, field.fieldId) } : {}),
  }
}

export function normalizeUserMetricLabels(component: DashboardComponent): DashboardComponent {
  const dataConfig = component.data_config
  if (!USER_DATASETS.has(component.dataset_code)
    || !dataConfig || !("metrics" in dataConfig)
    || !dataConfig.metrics?.some(metric => USER_METRIC_LABELS[metric.fieldId])) {
    return component
  }
  const renameTitle = (label: string) => dataConfig.metrics.reduce(
    (current, metric) => renameDefault(current, metric.fieldId), label,
  )

  // 仅转换旧默认名称, 保留自定义别名, 不修改服务端返回的原对象。
  return {
    ...component,
    title: renameTitle(component.title),
    style_config: component.style_config
      ? { ...component.style_config, title: renameTitle(component.style_config.title) }
      : component.style_config,
    data_config: {
      ...dataConfig,
      metrics: dataConfig.metrics.map(renameField),
      fieldOrder: dataConfig.fieldOrder?.map(field => field.fieldType === "metric" ? renameField(field) : field),
    },
  }
}
