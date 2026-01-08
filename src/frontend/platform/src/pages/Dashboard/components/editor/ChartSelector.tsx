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
import { ChevronRight, ChevronLeft } from "lucide-react"
import { toast } from "@/components/bs-ui/toast/use-toast"

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
  const [collapsed, setCollapsed] = useState(false) // 控制整体收起

  // 从 store 获取当前 dashboard 和组件
  const { currentDashboard } = useEditorDashboardStore()
  const { editingComponent } = useComponentEditorStore()
  
useEffect(() => {

  const config = editingComponent?.data_config
  
  if (config && 'linkedComponentIds' in config) {
    
    setSelectedCharts(config.linkedComponentIds || [])
    
    // 检查 queryConditions
    if (config.queryConditions) {
      const queryCond = config.queryConditions
      
      if (queryCond.displayType) {
        const displayTypeValue = queryCond.displayType === "single" ? "时间" : "时间范围"
        setDisplayType(displayTypeValue)
      }
      
      // 映射时间粒度
      if (queryCond.timeGranularity) {
        let timeGranularityValue = "年月日"
        if (queryCond.timeGranularity === "year_month") {
          timeGranularityValue = "年月"
        } else if (queryCond.timeGranularity === "year_month_day_hour") {
          timeGranularityValue = "年月日时"
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
            console.log('设置时间范围:', {
              startTime: Math.floor(startTime / 1000),
              endTime: Math.floor(endTime / 1000)
            })
            setTimeFilter({
              startTime: Math.floor(startTime / 1000),
              endTime: Math.floor(endTime / 1000)
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
    setDisplayType("时间范围")
    setTimeGranularity("年月日")
    setIsDefault(false)
    setTimeFilter(null)
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

  // 获取当前编辑的组件名称
  const componentName = editingComponent?.title || '未命名组件'

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
    toast({
      variant: 'success',
      description: '关联图表配置已保存',
    })
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

  // 收起状态显示
  if (collapsed) {
    return (
      <div className="border-r flex flex-col h-full w-12 shrink-0">
        <div className="h-full flex flex-col items-center justify-center cursor-pointer hover:bg-accent/50 transition-colors" 
             onClick={() => setCollapsed(false)}>
          <div className="writing-mode-vertical text-sm font-medium py-4">关联图表配置</div>
          <div className="mt-2">
            <ChevronRight className="h-4 w-4" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="border-r flex flex-col h-full w-[420px] shrink-0 bg-background">
      {/* 标题区域 */}
      <div className="px-4 py-3 border-b flex items-center justify-between bg-muted/20">
        <div>
          <h3 className="text-base font-semibold">关联图表配置</h3>
          {/* <p className="text-sm text-muted-foreground">组件：{componentName}</p> */}
        </div>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setCollapsed(true)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* 图表列表 */}
        <div className=" max-h-64 overflow-y-auto space-y-2">
          <div>选择关联图表</div>
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
        <div className="h-px bg-muted"></div>
        {/* 配置区 */}
        <div className="space-y-3">
          <div className="text-md font-medium">查询条件配置</div>
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
    </div>
  )
}