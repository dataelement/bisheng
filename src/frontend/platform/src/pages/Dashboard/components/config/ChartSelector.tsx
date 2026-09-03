"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/bs-ui/button"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem
} from "@/components/bs-ui/select"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { AdvancedDatePicker } from "../AdvancedDatePicker"
import { ListIndentIncrease, ListIndentDecrease } from "lucide-react"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { useTranslation } from "react-i18next"
import { useQuery } from "react-query"
import { getDatasets } from "@/controllers/API/dashboard"
import { DimensionFilterField } from "../../types/dataConfig"
import {
  QUERY_DIMENSION_CATEGORY_LABELS,
  queryDimensionCategoryForField,
} from "../../utils/queryDimensionCategories"

/* ================== 类型 ================== */
export interface ChartLinkConfig {
  chartIds: string[]
  displayType: string
  timeGranularity: string
  isDefault: boolean
  dateRange: {
    start: string
    end: string
    shortcutKey?: string
    isDynamic?: boolean
  }
  dimensionFields: DimensionFilterField[]
}

interface ChartSelectorProps {
  onSave?: (config: ChartLinkConfig) => void
  onCancel?: () => void
}

/* ================== 组件 ================== */
export default function ChartSelector({
  onSave,
  onCancel: onCancelChanges,
}: ChartSelectorProps) {
  const { t } = useTranslation("dashboard")
  const [selectedCharts, setSelectedCharts] = useState<string[]>([])
  const [displayType, setDisplayType] = useState(t("chartSelector.displayTypes.timeRange", "时间范围"))
  const [timeGranularity, setTimeGranularity] = useState(t("chartSelector.granularities.yearMonthDay", "年月日"))
  const [isDefault, setIsDefault] = useState(false)
  const [timeFilter, setTimeFilter] = useState<any>(null)
  const [dimensionFields, setDimensionFields] = useState<DimensionFilterField[]>([])
  const [collapsed, setCollapsed] = useState(false)

  // 从 store 获取当前 dashboard 和组件
  const { currentDashboard } = useEditorDashboardStore()
  const { editingComponent } = useComponentEditorStore()
  const { data: allDatasets = [], isLoading: datasetsLoading } = useQuery({
    queryKey: ['datasets'],
    queryFn: () => getDatasets()
  })
  useEffect(() => {
    const config = editingComponent?.data_config

    if (config && 'linkedComponentIds' in config) {
      setSelectedCharts(config.linkedComponentIds || [])
      setDimensionFields((config as any).dimensionFields || [])

      if ('queryConditions' in config && config.queryConditions) {
        const queryCond = config.queryConditions

        if (queryCond.displayType) {
          const displayTypeValue = queryCond.displayType === "single"
            ? t("chartSelector.displayTypes.time", "时间")
            : t("chartSelector.displayTypes.timeRange", "时间范围")
          setDisplayType(displayTypeValue)
        }

        // 映射时间粒度
        if (queryCond.timeGranularity) {
          let timeGranularityValue = t("chartSelector.granularities.yearMonthDay", "年月日")
          if (queryCond.timeGranularity === "year_month") {
            timeGranularityValue = t("chartSelector.granularities.yearMonth", "年月")
          } else if (queryCond.timeGranularity === "year_month_day_hour") {
            timeGranularityValue = t("chartSelector.granularities.yearMonthDayHour", "年月日时")
          }
          setTimeGranularity(timeGranularityValue)
        }

        // 设置默认值
        if (queryCond.hasDefaultValue !== undefined) {
          setIsDefault(queryCond.hasDefaultValue)
        }

        // 处理时间范围 - 修改这里
        if (queryCond.hasDefaultValue) {
          try {
            const startTime = queryCond.defaultValue.startDate
            const endTime = queryCond.defaultValue.endDate
            const mode = queryCond.defaultValue.mode || "fixed"

            // 处理shortcutKey
            let shortcutKey = ''
            if (queryCond.defaultValue.type === 'recent_days') {
              shortcutKey = `last_${queryCond.defaultValue.shortcutKey}`
            }

            if (startTime && endTime) {
              setTimeFilter({
                startTime: startTime,
                endTime: endTime,
                shortcutKey: shortcutKey,
                isDynamic: mode === "dynamic"
              })
            } else {
              setTimeFilter(null)
            }
          } catch (error) {
            setTimeFilter(null)
          }
        } else {
          setTimeFilter(null)
        }
      }
    } else {
      // 重置为默认值
      setSelectedCharts([])
      setDisplayType(t("chartSelector.displayTypes.timeRange"))
      setTimeGranularity(t("chartSelector.granularities.yearMonthDay"))
      setIsDefault(false)
      setTimeFilter(null)
      setDimensionFields([])
    }
  }, [editingComponent, t])
  const onCancel = () => {
    onCancelChanges?.()

    // 重置到编辑前的状态
    const config = editingComponent?.data_config

    if (config && 'linkedComponentIds' in config) {
      setSelectedCharts(config.linkedComponentIds || [])
      setDimensionFields((config as any).dimensionFields || [])

      if ('queryConditions' in config && config.queryConditions) {
        const queryCond = config.queryConditions

        if (queryCond.displayType) {
          const displayTypeValue = queryCond.displayType === "single"
            ? t("chartSelector.displayTypes.time", "时间")
            : t("chartSelector.displayTypes.timeRange", "时间范围")
          setDisplayType(displayTypeValue)
        }

        // 映射时间粒度
        if (queryCond.timeGranularity) {
          let timeGranularityValue = t("chartSelector.granularities.yearMonthDay", "年月日")
          if (queryCond.timeGranularity === "year_month") {
            timeGranularityValue = t("chartSelector.granularities.yearMonth", "年月")
          } else if (queryCond.timeGranularity === "year_month_day_hour") {
            timeGranularityValue = t("chartSelector.granularities.yearMonthDayHour", "年月日时")
          }
          setTimeGranularity(timeGranularityValue)
        }

        // 设置默认值
        if (queryCond.hasDefaultValue !== undefined) {
          setIsDefault(queryCond.hasDefaultValue)
        }

        // 处理时间范围
        if (queryCond.hasDefaultValue && queryCond.defaultValue?.type === 'custom') {
          try {
            const startTime = queryCond.defaultValue.startDate
            const endTime = queryCond.defaultValue.endDate
            const mode = queryCond.defaultValue.mode || "fixed"

            // 处理shortcutKey
            let shortcutKey = ''
            if (queryCond.defaultValue.type === 'recent_days' && queryCond.defaultValue.recentDays) {
              shortcutKey = `last_${queryCond.defaultValue.recentDays}`
            }

            if (startTime && endTime) {
              setTimeFilter({
                startTime: startTime,
                endTime: endTime,
                shortcutKey: shortcutKey,
                isDynamic: mode === "dynamic"
              })
            } else {
              setTimeFilter(null)
            }
          } catch (error) {
            setTimeFilter(null)
          }
        } else {
          setTimeFilter(null)
        }
      }
    } else {
      // 重置为默认值
      setSelectedCharts([])
      setDisplayType(t("chartSelector.displayTypes.timeRange"))
      setTimeGranularity(t("chartSelector.granularities.yearMonthDay"))
      setIsDefault(false)
      setTimeFilter(null)
      setDimensionFields([])
    }

    // 收起面板
    setCollapsed(!collapsed)
  }
  // 获取所有非查询类型的图表组件
  const charts = currentDashboard
    ? currentDashboard.components
      .filter(component =>
        !['query', 'dimension-filter'].includes(component.type)
      )
      .map(component => ({
        id: component.id,
        type: component.type,
        name: component.title || t("chartSelector.unnamedChart"),
        dataset: component.dataset_code || t("chartSelector.noDataset")
      }))
    : []

  // 客户反馈(2026-09-01): 查询组件的维度条件不像维度筛选组件那样绑死一个数据集——它可以关联
  // 不同数据集的图表，某个图表没有的维度对它就不生效（后端 convert_filters 静默跳过）。所以这里
  // 汇总所有数据集里属于这 4 个类别的维度，去重后给用户勾选，而不是像 DimensionFilterConfigurator
  // 那样先选数据集再看维度。
  const selectableDimensionFields = (() => {
    const byField = new Map<string, { field: string, name: string, datasetCode: string }>()
    allDatasets.forEach(dataset => {
      (dataset.schema_config?.dimensions || []).forEach((dimension: any) => {
        const field = String(dimension.field || "")
        if (!field || byField.has(field) || !queryDimensionCategoryForField(field)) return
        byField.set(field, { field, name: dimension.name, datasetCode: dataset.dataset_code })
      })
    })
    return Array.from(byField.values())
  })()

  const toggleDimensionField = (dimension: { field: string, name: string, datasetCode: string }) => {
    setDimensionFields(current => {
      const exists = current.some(item => item.fieldId === dimension.field)
      if (exists) return current.filter(item => item.fieldId !== dimension.field)
      return [
        ...current,
        {
          id: `${dimension.field}-${Date.now()}`,
          fieldId: dimension.field,
          fieldName: dimension.field,
          displayName: dimension.name,
          defaultValues: [],
          datasetCode: dimension.datasetCode,
        },
      ]
    })
  }

  const getDatasetName = (datasetCode: string): string => {
    if (!datasetCode || !allDatasets || allDatasets.length === 0) {
      return t("chartSelector.noDataset")
    }

    const dataset = allDatasets.find(d => d.dataset_code === datasetCode)
    return dataset?.dataset_name || datasetCode
  }
  /* 单选 */
  const toggleChart = (id: string) => {
    setSelectedCharts(prev =>
      prev.includes(id)
        ? prev.filter(c => c !== id)
        : [...prev, id]
    )
  }

  const toggleSelectAll = () => {
    const allChartIds = charts.map(c => c.id)
    if (selectedCharts.length === allChartIds.length) {
      setSelectedCharts([])
    } else {
      setSelectedCharts(allChartIds)
    }
  }

  /* 保存 */
  const handleSave = (e) => {


    const config: ChartLinkConfig = {
      chartIds: selectedCharts,
      displayType,
      timeGranularity,
      isDefault,
      dateRange: {
        start: timeFilter?.startTime ?? "",
        end: timeFilter?.endTime ?? "",
        shortcutKey: timeFilter?.shortcutKey,
        isDynamic: timeFilter?.isDynamic
      },
      dimensionFields
    }

    e.isTrusted && toast({
      variant: 'success',
      description: t("chartSelector.messages.saveSuccess"),
    })
    onSave?.(config)
  }

  // 计算是否全选
  const isAllSelected = selectedCharts.length === charts.length && charts.length > 0

  // 获取粒度对应的 granularity
  const getGranularity = () => {
    switch (timeGranularity) {
      case t("chartSelector.granularities.yearMonth"): return "month"
      case t("chartSelector.granularities.yearMonthDayHour"): return "hour"
      default: return "day"
    }
  }

  // 获取展示类型对应的 mode
  const getMode = () => {
    return displayType === t("chartSelector.displayTypes.timeRange") ? "range" : "single"
  }

  // 收起状态显示
  if (collapsed) {
    return (
      <div className="border-r flex flex-col h-full w-12 shrink-0">
        <div className="h-full flex flex-col items-center justify-center cursor-pointer hover:bg-accent/50 transition-colors"
          onClick={() => setCollapsed(false)}>
          <div className="writing-mode-vertical text-sm font-medium py-4">
            {t("chartSelector.messages.collapse")}
          </div>
          <div className="mt-2">
            <ListIndentDecrease className="h-4 w-4" />
          </div>
        </div>
      </div>
    )
  }


  return (
    <div className="border-r flex flex-col h-full w-[440px] shrink-0 bg-background relative">
      <div className="px-4 py-3 border-b flex items-center justify-between bg-muted/20 shrink-0">
        <div>
          <h3 className="text-base font-semibold">
            {t("chartSelector.title")}
          </h3>
        </div>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setCollapsed(true)}>
          <ListIndentIncrease className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div className="space-y-2">
          <div>{t("chartSelector.selectCharts")}</div>

          {/* 全选 */}
          <div className="flex items-center gap-2">
            <Checkbox
              checked={isAllSelected}
              onCheckedChange={toggleSelectAll}
            />
            <span className="font-medium">
              {t("chartSelector.selectAll")}
            </span>
          </div>

          {/* 单个图表 */}
          <div className="max-h-40 overflow-y-auto space-y-2">
            {charts.length > 0 ? (
              charts.map(chart => (
                <div key={chart.id} className="flex items-center gap-2">
                  <Checkbox
                    checked={selectedCharts.includes(chart.id)}
                    onCheckedChange={() => toggleChart(chart.id)}
                  />
                  <span className="text-sm flex">
                    <img
                      src={`${__APP_ENV__.BASE_URL}/assets/dashboard/${chart.type}.png`}
                      className="w-4 h-4 shrink-0 mt-0.5 mr-1"
                      alt={chart.type}
                    />
                    {chart.name}
                    {
                      chart.dataset && (
                        <span className="text-muted-foreground text-xs ml-4 mt-0.5">
                          {getDatasetName(chart.dataset)}
                        </span>
                      )
                    }
                  </span>
                </div>
              ))
            ) : (
              <div className="text-sm text-muted-foreground pl-4">
                {t("chartSelector.messages.noCharts")}
              </div>
            )}
          </div>

          <div className="h-px bg-muted"></div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-md font-medium">维度条件</span>
              <span className="text-xs text-muted-foreground">
                {dimensionFields.length}/{selectableDimensionFields.length}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              知识库大类、知识分类、组织架构、业务域；某个图表没有配置的维度，条件对它不生效。
            </p>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-border p-2">
              {selectableDimensionFields.map(dimension => {
                const checked = dimensionFields.some(field => field.fieldId === dimension.field)
                const category = queryDimensionCategoryForField(dimension.field)
                return (
                  <label
                    key={dimension.field}
                    className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent/50"
                  >
                    <Checkbox checked={checked} onCheckedChange={() => toggleDimensionField(dimension)} />
                    <span className="truncate" title={dimension.name}>{dimension.name}</span>
                    {category && (
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                        {QUERY_DIMENSION_CATEGORY_LABELS[category]}
                      </span>
                    )}
                  </label>
                )
              })}
              {!selectableDimensionFields.length && (
                <p className="py-4 text-center text-xs text-muted-foreground">
                  {datasetsLoading ? "加载中…" : "暂无可选维度"}
                </p>
              )}
            </div>
          </div>

          <div className="h-px bg-muted"></div>

          <div className="space-y-3">
            <div className="text-md font-medium">
              {t("chartSelector.config")}
            </div>

            <div className="space-y-1">
              <label className="text-sm">
                {t("chartSelector.displayType")}
              </label>
              <Select value={displayType} onValueChange={setDisplayType}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={t("chartSelector.displayTypes.timeRange")}>
                    {t("chartSelector.displayTypes.timeRange")}
                  </SelectItem>
                  <SelectItem value={t("chartSelector.displayTypes.time")}>
                    {t("chartSelector.displayTypes.time")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* 时间粒度 */}
            <div className="space-y-1">
              <label className="text-sm">
                {t("chartSelector.timeGranularity")}
              </label>
              <Select value={timeGranularity} onValueChange={setTimeGranularity}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={t("chartSelector.granularities.yearMonth")}>
                    {t("chartSelector.granularities.yearMonth")}
                  </SelectItem>
                  <SelectItem value={t("chartSelector.granularities.yearMonthDay")}>
                    {t("chartSelector.granularities.yearMonthDay")}
                  </SelectItem>
                  <SelectItem value={t("chartSelector.granularities.yearMonthDayHour")}>
                    {t("chartSelector.granularities.yearMonthDayHour")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* 默认值 */}
            <div className="flex items-center gap-2">
              <Checkbox
                checked={isDefault}
                onCheckedChange={() => setIsDefault(prev => !prev)}
              />
              <span className="text-sm">
                {t("chartSelector.setDefault")}
              </span>
            </div>

            {isDefault && (
              <div className="space-y-1 flex flex-1 w-full">
                <AdvancedDatePicker
                  granularity={getGranularity()}
                  mode={getMode()}
                  value={timeFilter}
                  onChange={(val) => setTimeFilter(val)}
                  placeholder={t("chartSelector.datePicker.placeholder")}
                />
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="border-t bg-background p-4 shrink-0">
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            onClick={onCancel}
            className="flex-1"
          >
            {t("chartSelector.buttons.cancel")}
          </Button>
          <Button
            id="query_save"
            onClick={handleSave}
            className="flex-1"
          >
            {t("chartSelector.buttons.save")}
          </Button>
        </div>
      </div>
    </div>
  )
}
