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

/* ================== 类型 ================== */
export interface ChartLinkConfig {
  chartIds: string[]
  displayType: string
  timeGranularity: string
  isDefault: boolean
  dateRange: {
    start: string
    end: string
  }
}

interface ChartSelectorProps {
  onSave?: (config: ChartLinkConfig) => void
  onCancel?: () => void
}

/* ================== 组件 ================== */
export default function ChartSelector({
  onSave,
  // onCancel
}: ChartSelectorProps) {
  const { t } = useTranslation("dashboard")
  const [selectedCharts, setSelectedCharts] = useState<string[]>([])
  const [displayType, setDisplayType] = useState(t("chartSelector.displayTypes.timeRange", "时间范围"))
  const [timeGranularity, setTimeGranularity] = useState(t("chartSelector.granularities.yearMonthDay", "年月日"))
  const [isDefault, setIsDefault] = useState(false)
  const [timeFilter, setTimeFilter] = useState<any>(null)
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

      if (config.queryConditions) {
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

            if (startTime && endTime) {
              setTimeFilter({
                startTime: startTime,
                endTime: endTime
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
    }
  }, [editingComponent, t])
  const onCancel = () => {
    setCollapsed(!collapsed)
  }
  // 获取所有非查询类型的图表组件
  const charts = currentDashboard
    ? currentDashboard.components
      .filter(component =>
        component.type !== 'query'
      )
      .map(component => ({
        id: component.id,
        type: component.type,
        name: component.title || t("chartSelector.unnamedChart"),
        dataset: component.dataset_code || t("chartSelector.noDataset")
      }))
    : []

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
        end: timeFilter?.endTime ?? ""
      }
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
    <div className="border-r flex flex-col h-full w-[420px] shrink-0 bg-background relative">
      {/* 标题区域 */}
      <div className="px-4 py-3 border-b flex items-center justify-between bg-muted/20">
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
        {/* 图表列表 */}
        <div className="max-h-64 overflow-y-auto space-y-2">
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

        {/* 配置区 */}
        <div className="space-y-3">
          <div className="text-md font-medium">
            {t("chartSelector.config")}
          </div>

          {/* 展示类型 */}
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

          {/* 时间范围 */}
          {isDefault && <div className="space-y-1 flex flex-1 w-full">
            <AdvancedDatePicker
              granularity={getGranularity()}
              mode={getMode()}
              value={timeFilter}
              onChange={(val) => setTimeFilter(val)}
              placeholder={t("chartSelector.datePicker.placeholder")}
            />
          </div>}
        </div>

        {/* 底部按钮 */}
        <div className="border-t bg-background p-4 absolute bottom-0 left-0 right-0">
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
    </div>
  )
}