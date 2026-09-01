"use client"

import { MultiSelect, Option } from "@/components/bs-ui/multiSelect.tsx"
import { getFieldEnums } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  DashboardComponent,
  DimensionFilterConfig,
} from "../../types/dataConfig"
import { ORG_LEVEL_ORDER, orgLevelForField } from "../../utils/groupCrossTabRows"

// Customer feedback (2026-09-01): the "上传人名称" filter dropdown must show each
// uploader's department alongside their name ("部门-姓名"), to disambiguate same-named
// uploaders — but ONLY in this one dropdown, not in the crosstab/chart legends (those
// already have their own separate person+department merge, see mergePersonDedupValues
// in groupCrossTabRows.ts). Reuses the existing label_field sub-aggregation the backend
// already supports (dashboard.py::get_dataset_field_enums) — no backend change needed.
const UPLOADER_NAME_FIELD_ID = "uploader_user_name"
const UPLOADER_DEPARTMENT_FIELD_ID = "uploader_department_name"

// F058 AC-03: among configured org-hierarchy fields (公司/部门/科室/班组，both "所属"
// belonging_* and "原始上传库" uploader_* variants), enforce a fixed relative display
// order — company -> dept -> office -> squad. Non-org fields keep their configured
// position; org fields are only reordered relative to each other (stable sort).
function sortDimensionFilterFields<T extends { fieldId: string }>(fields: T[]): T[] {
  return [...fields].sort((a, b) => {
    const levelA = orgLevelForField(a.fieldId)
    const levelB = orgLevelForField(b.fieldId)
    if (!levelA || !levelB) return 0
    return ORG_LEVEL_ORDER.indexOf(levelA) - ORG_LEVEL_ORDER.indexOf(levelB)
  })
}

interface DimensionFilterProps {
  component: DashboardComponent
  isDark?: boolean
}

export function DimensionFilter({ component, isDark }: DimensionFilterProps) {
  const config = component.data_config as DimensionFilterConfig
  const storedValues = useEditorDashboardStore(
    state => state.dimensionFilterParams[component.id]
  )
  const refreshCharts = useEditorDashboardStore(
    state => state.refreshChartsByDimensionFilter
  )
  const defaults = useMemo(
    () => Object.fromEntries(
      (config.fields || []).map(field => [field.fieldId, field.defaultValues || []])
    ),
    [config.fields]
  )
  const [selectedValues, setSelectedValues] = useState<Record<string, string[]>>(
    storedValues || defaults
  )
  const [options, setOptions] = useState<Record<string, Option[]>>({})
  const [loading, setLoading] = useState<Record<string, boolean>>({})
  const listRequestVersions = useRef<Record<string, number>>({})
  const pendingRequestCounts = useRef<Record<string, number>>({})

  const loadOptions = useCallback(async (
    fieldId: string,
    labelFieldId?: string,
    keyword = "",
    exactValues: string[] = []
  ) => {
    if (!component.dataset_code || !fieldId) return []
    const effectiveLabelFieldId = fieldId === UPLOADER_NAME_FIELD_ID
      ? UPLOADER_DEPARTMENT_FIELD_ID
      : labelFieldId
    const isExactLookup = exactValues.length > 0
    const requestVersion = isExactLookup
      ? 0
      : (listRequestVersions.current[fieldId] || 0) + 1
    if (!isExactLookup) {
      listRequestVersions.current[fieldId] = requestVersion
    }
    pendingRequestCounts.current[fieldId] =
      (pendingRequestCounts.current[fieldId] || 0) + 1
    setLoading(current => ({ ...current, [fieldId]: true }))
    try {
      const response = await getFieldEnums({
        dataset_code: component.dataset_code,
        field: fieldId,
        labelField: effectiveLabelFieldId,
        exactValues,
        page: 1,
        pageSize: 50,
        keyword,
      })
      const nextOptions = (response.options || response.enums || []).map((option: any) => {
        const value = String(option?.value ?? option)
        const label = String(option?.label ?? option)
        if (fieldId === UPLOADER_NAME_FIELD_ID && label && label !== value) {
          return { label: `${label}-${value}`, value }
        }
        return { label, value }
      })
      if (
        !isExactLookup &&
        listRequestVersions.current[fieldId] === requestVersion
      ) {
        setOptions(current => ({ ...current, [fieldId]: nextOptions }))
      }
      return nextOptions
    } finally {
      const pendingCount = Math.max(
        0,
        (pendingRequestCounts.current[fieldId] || 1) - 1
      )
      pendingRequestCounts.current[fieldId] = pendingCount
      setLoading(current => ({
        ...current,
        [fieldId]: pendingCount > 0,
      }))
    }
  }, [component.dataset_code])

  useEffect(() => {
    const nextValues = storedValues || defaults
    setSelectedValues(nextValues)
  }, [defaults, storedValues])

  useEffect(() => {
    config.fields?.forEach(field => {
      void loadOptions(field.fieldId, field.labelFieldId)
    })
  }, [component.id, config.fields, loadOptions])

  if (!config.fields?.length) {
    return (
      <div className="flex size-full items-center justify-center rounded-md border border-dashed border-border bg-muted/20 text-sm text-muted-foreground">
        请在右侧配置要筛选的维度
      </div>
    )
  }

  const sortedFields = sortDimensionFilterFields(config.fields)

  return (
    <div
      className={`flex size-full items-center gap-3 overflow-x-auto px-2 ${
        isDark ? "text-slate-100" : "text-slate-900"
      }`}
    >
      {sortedFields.map(field => {
        const isOrgField = Boolean(orgLevelForField(field.fieldId))
        const fieldOptions = options[field.fieldId] || []
        const handleSelectAll = () => {
          const nextValues = {
            ...selectedValues,
            [field.fieldId]: fieldOptions.map(option => option.value),
          }
          setSelectedValues(nextValues)
          refreshCharts(component, nextValues)
        }
        return (
          <div key={field.id} className="min-w-52 flex-1 space-y-1">
            <div className="flex items-center justify-between gap-2">
              <label
                htmlFor={`${component.id}-${field.id}`}
                className="block truncate text-xs font-medium text-muted-foreground"
                title={field.displayName}
              >
                {field.displayName}
              </label>
              {isOrgField && (
                <button
                  type="button"
                  className="shrink-0 text-xs text-primary hover:underline disabled:pointer-events-none disabled:opacity-50"
                  disabled={!fieldOptions.length}
                  onClick={handleSelectAll}
                >
                  全选
                </button>
              )}
            </div>
            <MultiSelect
              id={`${component.id}-${field.id}`}
              options={fieldOptions}
              value={selectedValues[field.fieldId] || []}
              onValueChange={values => {
                const nextValues = { ...selectedValues, [field.fieldId]: values }
                setSelectedValues(nextValues)
                refreshCharts(component, nextValues)
              }}
              onSearch={keyword => {
                void loadOptions(field.fieldId, field.labelFieldId, keyword)
              }}
              onFetchByIds={async ids => {
                const result = await loadOptions(
                  field.fieldId,
                  field.labelFieldId,
                  "",
                  ids
                )
                const exact = new Map(
                  result.map(option => [option.value, option])
                )
                return ids.map(id => exact.get(id) || { label: id, value: id })
              }}
              loading={loading[field.fieldId]}
              multiple
              searchable
              clearable
              maxDisplayed={2}
              placeholder={`全部${field.displayName}`}
              searchPlaceholder={`搜索${field.displayName}`}
              emptyMessage="暂无可选项"
              triggerClassName="no-drag h-9 bg-background"
              contentClassName="min-w-64"
            />
          </div>
        )
      })}
    </div>
  )
}
