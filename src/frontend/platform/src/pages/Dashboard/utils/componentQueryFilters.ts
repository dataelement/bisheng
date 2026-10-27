import type { DatePickerValue } from "../components/AdvancedDatePicker"
import { QueryConfig, TimeFilter, TimeRangeMode, TimeRangeType } from "../types/dataConfig"

interface ComponentQueryParams {
  queryComponentParams?: DatePickerValue
  queryConditions?: Pick<QueryConfig["queryConditions"], "hasDefaultValue" | "defaultValue">
  dimensionFilters?: { fieldId: string, values: unknown[] }[]
}

// 查询与导出使用同一份已经应用到图表的筛选参数。
export function componentQueryFilters(queryParams: ComponentQueryParams[] = []) {
  const timeFilters: TimeFilter[] = queryParams.flatMap(({ queryComponentParams: value, queryConditions }) => {
    if (value) {
      return [{
        type: value.shortcutKey ? TimeRangeType.RECENT_DAYS : TimeRangeType.CUSTOM,
        mode: value.isDynamic ? TimeRangeMode.Dynamic : TimeRangeMode.Fixed,
        recentDays: value.shortcutKey ? Number(value.shortcutKey.replace("last_", "")) : undefined,
        startDate: value.startTime,
        endDate: value.endTime,
      }]
    }
    return queryConditions?.hasDefaultValue && queryConditions.defaultValue ? [queryConditions.defaultValue] : []
  })
  return {
    timeFilters,
    dimensionFilters: queryParams.flatMap(param => param.dimensionFilters || []),
  }
}
