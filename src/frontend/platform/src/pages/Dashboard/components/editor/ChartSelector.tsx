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
  onCancel
}: ChartSelectorProps) {
  const [selectedCharts, setSelectedCharts] = useState<string[]>([])
  const [displayType, setDisplayType] = useState("时间范围")
  const [timeGranularity, setTimeGranularity] = useState("年月日")
  const [isDefault, setIsDefault] = useState(false)
  const [timeFilter, setTimeFilter] = useState<any>(null)

  const [collapsed, setCollapsed] = useState(false)
  // 从 store 获取当前 dashboard 和组件
  const { currentDashboard } = useEditorDashboardStore()
  const { editingComponent } = useComponentEditorStore()
    useEffect(() => {
    if (editingComponent?.query_config) {
      const config = editingComponent.query_config

      if (config.linkedComponentIds) {
        setSelectedCharts(config.linkedComponentIds)
      }
      if (config.displayType) {
        setDisplayType(config.displayType)
      }
      
      if (config.timeGranularity) {
        setTimeGranularity(config.timeGranularity)
      }
      
      if (config.isDefault !== undefined) {
        setIsDefault(config.isDefault)
      }
      
      if (config.defaultDateRange?.start) {
        const startDate = new Date(config.defaultDateRange.start)
        const endDate = new Date(config.defaultDateRange.end)
        
        if (!isNaN(startDate.getTime())) {
          setTimeFilter({
            startTime: Math.floor(startDate.getTime() / 1000),
            endTime: Math.floor(endDate.getTime() / 1000)
          })
        }
      }
    }
  }, [editingComponent])
  // 获取所有非查询类型的图表组件
  const charts = currentDashboard 
    ? currentDashboard.components
        .filter(component => 
          component.type !== 'query' && 
          component.type !== 'metric'
        )
        .map(component => ({
          id: component.id,
          name: component.title || '未命名图表',
          dataset: component.dataset_code || '未设置数据集'
        }))
    : []

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
  const toggleCollapse = () => setCollapsed(prev => !prev)
  /* 保存 */
  const handleSave = () => {
    let finalStartDate = ""
    let finalEndDate = ""
    
    if (timeFilter && timeFilter.startTime) {
      // 将时间戳转换为日期字符串
      const startDateObj = new Date(timeFilter.startTime * 1000)
      const endDateObj = new Date(timeFilter.endTime * 1000)
      
      // 根据时间粒度格式化
      const year = startDateObj.getFullYear()
      const month = String(startDateObj.getMonth() + 1).padStart(2, '0')
      const day = String(startDateObj.getDate()).padStart(2, '0')
      const hour = String(startDateObj.getHours()).padStart(2, '0')
      
      if (timeGranularity === "年月") {
        finalStartDate = `${year}-${month}`
        finalEndDate = `${year}-${month}`
      } else if (timeGranularity === "年月日时") {
        const endYear = endDateObj.getFullYear()
        const endMonth = String(endDateObj.getMonth() + 1).padStart(2, '0')
        const endDay = String(endDateObj.getDate()).padStart(2, '0')
        const endHour = String(endDateObj.getHours()).padStart(2, '0')
        
        if (displayType === "时间") {
          // 时间点模式
          finalStartDate = `${year}-${month}-${day} ${hour}:00`
          finalEndDate = `${year}-${month}-${day} ${hour}:00`
        } else {
          // 时间范围模式
          finalStartDate = `${year}-${month}-${day} ${hour}:00`
          finalEndDate = `${endYear}-${endMonth}-${endDay} ${endHour}:00`
        }
      } else {
        // 年月日
        if (displayType === "时间") {
          // 时间点模式
          finalStartDate = `${year}-${month}-${day}`
          finalEndDate = `${year}-${month}-${day}`
        } else {
          // 时间范围模式
          const endYear = endDateObj.getFullYear()
          const endMonth = String(endDateObj.getMonth() + 1).padStart(2, '0')
          const endDay = String(endDateObj.getDate()).padStart(2, '0')
          
          finalStartDate = `${year}-${month}-${day}`
          finalEndDate = `${endYear}-${endMonth}-${endDay}`
        }
      }
    }
    
    const config: ChartLinkConfig = {
      chartIds: selectedCharts,
      displayType,
      timeGranularity,
      isDefault,
      dateRange: {
        start: finalStartDate,
        end: finalEndDate
      }
    }
    
    console.log('保存的配置:', config)
    onSave?.(config)
  }

  // 计算是否全选（用于复选框的 checked 状态）
  const isAllSelected = selectedCharts.length === charts.length && charts.length > 0

  // 获取粒度对应的 granularity
  const getGranularity = () => {
    switch (timeGranularity) {
      case "年月": return "month"
      case "年月日时": return "hour"
      default: return "day"
    }
  }

  // 获取展示类型对应的 mode
  const getMode = () => {
    return displayType === "时间范围" ? "range" : "single"
  }

  return (
    <div className="w-[420px] bg-background border rounded-lg shadow-lg p-4 space-y-4">
      <h3 className="text-lg font-medium">选择关联图表</h3>

      {/* 图表列表 */}
      <div className="border rounded-md p-2 max-h-64 overflow-y-auto space-y-2">
        {/* 全选 */}
        <div className="flex items-center gap-2">
          <Checkbox
            checked={isAllSelected}
            onCheckedChange={toggleSelectAll}
          />
          <span className="font-medium">全选</span>
        </div>

        {/* 单个图表 */}
        {charts.map(chart => (
          <div
            key={chart.id}
            className="flex items-center gap-2 pl-4"
          >
            <Checkbox
              checked={selectedCharts.includes(chart.id)}
              onCheckedChange={() => toggleChart(chart.id)}
            />
            <span className="text-sm">
              {chart.name}
              {chart.dataset && (
                <span className="text-muted-foreground ml-1">
                  ({chart.dataset})
                </span>
              )}
            </span>
          </div>
        ))}
      </div>

      {/* 配置区 */}
      <div className="space-y-3">
        {/* 展示类型 */}
        <div className="space-y-1">
          <label className="text-sm">展示类型</label>
          <Select value={displayType} onValueChange={setDisplayType}>
            <SelectTrigger className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="时间范围">时间范围</SelectItem>
              <SelectItem value="时间">时间</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* 时间粒度 */}
        <div className="space-y-1">
          <label className="text-sm">时间粒度</label>
          <Select value={timeGranularity} onValueChange={setTimeGranularity}>
            <SelectTrigger className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="年月">年月</SelectItem>
              <SelectItem value="年月日">年月日</SelectItem>
              <SelectItem value="年月日时">年月日时</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* 默认值 */}
        <div className="flex items-center gap-2">
          <Checkbox
            checked={isDefault}
            onCheckedChange={() => setIsDefault(prev => !prev)}
          />
          <span className="text-sm">设置为默认值</span>
        </div>

        {/* 时间范围 - 始终使用AdvancedDatePicker */}
        <div className="space-y-1">
          <AdvancedDatePicker
            granularity={getGranularity()}
            mode={getMode()}
            value={timeFilter}
            onChange={(val) => {
              console.log("时间选择变化:", val)
              setTimeFilter(val)
            }}
            placeholder={`选择${displayType}`}
          />
        </div>
      </div>

      {/* 底部按钮 */}
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="outline" onClick={onCancel}>
          取消
        </Button>
        <Button onClick={handleSave}>
          保存
        </Button>
      </div>
    </div>
  )
}