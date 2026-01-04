"use client"

import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { ChevronDown, ChevronLeft, ChevronRight, GripVertical, Plus, X } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { ChartType, ComponentStyleConfig, DataConfig } from "../../types/dataConfig"
import ChartSelector from "./ChartSelector"
import { DashboardConfigPanel } from "./DashboardConfigPanel"
import { DatasetField, DatasetSelector } from "./DatasetSelector"
import { DimensionBlock } from "./DimensionBlock"
import { FilterConditionDialog } from "./FilterConditionDialog"
import { StyleConfigPanel } from "./StyleConfigPanel"
import { TimeRangePicker } from "./TimeRangePicker"

// 图表类型选项
export const CHART_TYPES: {
  label: string;
  value: ChartType;
}[] = [
    { label: "基础柱状图", value: ChartType.Bar },
    { label: "堆叠柱状图", value: ChartType.StackedBar },
    { label: "分组柱状图", value: ChartType.GroupedBar },
    { label: "基础条形图", value: ChartType.HorizontalBar },
    { label: "堆叠条形图", value: ChartType.StackedHorizontalBar },
    { label: "分组条形图", value: ChartType.GroupedHorizontalBar },
    { label: "基础折线图", value: ChartType.Line },
    { label: "面积图", value: ChartType.Area },
    { label: "堆叠折线图", value: ChartType.StackedLine },
    { label: "饼状图", value: ChartType.Pie },
    { label: "环状图", value: ChartType.Donut },
    { label: "指标卡", value: ChartType.Metric },
    { label: "查询组件", value: ChartType.Query }
  ];

export function ComponentConfigDrawer() {
  const { editingComponent, updateEditingComponent } = useComponentEditorStore();
  const { refreshChart } = useEditorDashboardStore();

  // 折叠状态
  const [configCollapsed, setConfigCollapsed] = useState({
    basic: false,
    data: false,
    category: false,
    stack: false,
    value: false
  })

  // 样式配置
  const [styleConfig, setStyleConfig] = useState<ComponentStyleConfig>({
    themeColor: "#4ac5ff",
    bgColor: "#ffffff",
    titleFontSize: 14,
    titleBold: false,
    titleItalic: false,
    titleUnderline: false,
    titleAlign: "left",
    axis: "x",
    axisTitle: "",
    axisFontSize: 14,
    axisBold: false,
    axisItalic: false,
    axisUnderline: false,
    axisAlign: "left",
    legendPosition: "bottom",
    legendFontSize: 14,
    legendBold: false,
    legendItalic: false,
    legendUnderline: false,
    legendAlign: "left",
    showLegend: true,
    showAxis: true,
    showDataLabel: true,
    showGrid: true,
  })

  const [configTab, setConfigTab] = useState<"basic" | "style">("basic")
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [chartType, setChartType] = useState<ChartType>(editingComponent?.type || 'bar')
  const [title, setTitle] = useState(editingComponent?.title || '')
  const [limitType, setLimitType] = useState<"all" | "limit">("limit")
  const [limitValue, setLimitValue] = useState("1000")
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")

  // 维度数据状态
  const [categoryDimensions, setCategoryDimensions] = useState<any[]>([])
  const [stackDimensions, setStackDimensions] = useState<any[]>([])
  const [valueDimensions, setValueDimensions] = useState<any[]>([])
  const [filters, setFilters] = useState<any[]>([])
  const [dragOverSection, setDragOverSection] = useState<string | null>(null)
  const [filterGroup, setFilterGroup] = useState(null)

  // 对话框状态
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)
  const [editingDimension, setEditingDimension] = useState<any>(null)
  const [editingFilter, setEditingFilter] = useState<any>({ fieldName: '', operator: 'eq', value: '' })
  const [datasetFields, setDatasetFields] = useState<DatasetField[]>([])

  const [sortPriorityOrder, setSortPriorityOrder] = useState<string[]>([])
  useEffect(() => {
    const allFields = [
      ...categoryDimensions.map(d => ({ ...d, section: 'category' as const })),
      ...stackDimensions.map(d => ({ ...d, section: 'stack' as const })),
      ...valueDimensions.map(d => ({ ...d, section: 'value' as const }))
    ]

    const newOrder = allFields.map(field => field.id)
    setSortPriorityOrder(newOrder)
  }, [categoryDimensions.length, stackDimensions.length, valueDimensions.length])
  // 初始化
  useEffect(() => {
    if (editingComponent) {
      console.log('初始化组件配置:', editingComponent)
      setChartType(editingComponent.type)
      setStyleConfig(editingComponent.style_config || {})
      setTitle(editingComponent.title || '')

      // 清空之前的维度数据
      setCategoryDimensions([])
      setStackDimensions([])
      setValueDimensions([])

      // 初始化维度数据
      if (editingComponent.data_config) {
        // 初始化维度（category）
        if (editingComponent.data_config.dimensions) {
          const categoryDims = editingComponent.data_config.dimensions.map((dim, index) => ({
            id: `category_${index}_${Date.now()}`,
            fieldId: dim.fieldId,
            name: dim.fieldCode,
            displayName: dim.displayName || dim.fieldName,
            originalName: dim.fieldName,
            sort: dim.sort || 'none',
            sortPriority: 0,
            fieldType: 'dimension'
          }))
          setCategoryDimensions(categoryDims)
        }

        // 初始化指标（value）
        if (editingComponent.data_config.metrics) {
          const valueDims = editingComponent.data_config.metrics.map((metric, index) => ({
            id: `value_${index}_${Date.now()}`,
            fieldId: metric.fieldId,
            name: metric.fieldCode,
            displayName: metric.displayName || metric.fieldName,
            originalName: metric.fieldName,
            sort: metric.sort || 'none',
            sortPriority: 0,
            fieldType: 'metric',
            aggregation: metric.aggregation || 'sum'
          }))
          setValueDimensions(valueDims)
        }

        // 初始化筛选条件
        if (editingComponent.data_config.filters) {
          const conditions = editingComponent.data_config.filters.map(filter => ({
            id: filter.id || crypto.randomUUID(),
            fieldCode: filter.fieldCode || filter.fieldId,
            operator: filter.operator || 'eq',
            value: filter.value,
            fieldType: filter.filterType || 'string'
          }))

          setFilterGroup({
            logic: 'and',
            conditions
          })
        }
      }
    } else {
      // 清空所有状态
      setCategoryDimensions([])
      setStackDimensions([])
      setValueDimensions([])
      setFilterGroup(null)
    }
  }, [editingComponent])

  // 数据集改变
  const handleDatasetChange = (datasetCode: string) => {
    if (editingComponent) {
      updateEditingComponent({ dataset_code: datasetCode })
    }
  }

  // 拖拽处理函数
  const handleDragStart = (e: React.DragEvent, data: any) => {
    e.dataTransfer.setData('application/json', JSON.stringify(data))
  }

  const handleDragOver = (e: React.DragEvent, section: 'category' | 'stack' | 'value') => {
    e.preventDefault()
    setDragOverSection(section)
  }

  const handleDragLeave = () => {
    setDragOverSection(null)
  }

  const handleDrop = (e: React.DragEvent, section: 'category' | 'stack' | 'value') => {
    e.preventDefault()
    e.stopPropagation()

    const dataStr = e.dataTransfer.getData('application/json')
    if (!dataStr) return

    try {
      const data = JSON.parse(dataStr)
      const fieldType = data.fieldType || 'dimension' // 获取字段类型

      if (
        (fieldType === 'metric' && (section === 'category' || section === 'stack')) ||
        (fieldType === 'dimension' && section === 'value')
      ) {
        console.warn(`字段类型 ${fieldType} 不能拖拽到 ${section} 区域`)
        setDragOverSection(null)
        return
      }
      // 添加维度逻辑
      const addDimension = (section: 'category' | 'stack' | 'value', data: any) => {
        const fieldId = data.id || data.name || `field_${Date.now()}`
        const name = data.name || data.displayName || fieldId

        // 检查是否已存在
        let currentDimensions: any[] = []
        if (section === 'category') currentDimensions = categoryDimensions
        if (section === 'stack') currentDimensions = stackDimensions
        if (section === 'value') currentDimensions = valueDimensions

        const alreadyExists = currentDimensions.some(dim => dim.fieldId === fieldId)
        if (alreadyExists) return

        const displayName = data.displayName || name
        const originalName = data.name || name

        const newDimension = {
          id: `${section}_${Date.now()}`,
          fieldId,
          name,
          displayName,
          originalName,
          sort: 'none' as const,
          sortPriority: 0,
          fieldType
        }

        if (section === 'category') {
          if (categoryDimensions.length >= 2) return
          setCategoryDimensions(prev => [...prev, newDimension])
        } else if (section === 'stack') {
          setStackDimensions(prev => [...prev, newDimension])
        } else if (section === 'value') {
          setValueDimensions(prev => [...prev, newDimension])
        }
      }

      addDimension(section, data)
      setDragOverSection(null)
    } catch (error) {
      console.error('拖拽数据解析失败:', error)
    }
  }

  // 删除维度
  const handleDeleteDimension = (section: 'category' | 'stack' | 'value', dimensionId: string) => {
    if (section === 'category') setCategoryDimensions(prev => prev.filter(d => d.id !== dimensionId))
    if (section === 'stack') setStackDimensions(prev => prev.filter(d => d.id !== dimensionId))
    if (section === 'value') setValueDimensions(prev => prev.filter(d => d.id !== dimensionId))
  }

  // 排序改变
  const handleSortChange = (section: 'category' | 'stack' | 'value', dimensionId: string, sortValue: 'none' | 'asc' | 'desc') => {
    const updateDimensions = (prev: any[]) =>
      prev.map(d => d.id === dimensionId ? { ...d, sort: sortValue } : d)

    if (section === 'category') setCategoryDimensions(updateDimensions)
    if (section === 'stack') setStackDimensions(updateDimensions)
    if (section === 'value') setValueDimensions(updateDimensions)
  }

  // 编辑显示名称
  const openEditDialog = (section: 'category' | 'stack' | 'value', dimensionId: string, originalName: string, displayName: string) => {
    setEditingDimension({ id: dimensionId, section, originalName, displayName })
    setEditDialogOpen(true)
  }

  const saveDisplayName = () => {
    if (editingDimension) {
      const updateDimensions = (prev: any[]) =>
        prev.map(d => d.id === editingDimension.id ? { ...d, displayName: editingDimension.displayName } : d)

      if (editingDimension.section === 'category') setCategoryDimensions(updateDimensions)
      if (editingDimension.section === 'stack') setStackDimensions(updateDimensions)
      if (editingDimension.section === 'value') setValueDimensions(updateDimensions)

      setEditDialogOpen(false)
      setEditingDimension(null)
    }
  }

  // 筛选条件
  const handleAddFilter = () => {
    setFilterGroup({
      logic: 'and',
      conditions: [{ id: crypto.randomUUID() }]
    })
    setFilterDialogOpen(true)
  }
  const handleEditFilter = () => {
    if (filterGroup) {
      setFilterDialogOpen(true)
    } else {
      handleAddFilter()
    }
  }

  const handleDeleteFilter = () => {
    setFilterGroup(null)
  }

  const handleSaveFilter = (newFilterGroup: any) => {
    setFilterGroup(newFilterGroup)
    setFilterDialogOpen(false)
  }

  // 切换折叠
  const toggleCollapse = (section: keyof typeof configCollapsed) => {
    setConfigCollapsed(prev => ({ ...prev, [section]: !prev[section] }))
  }
  // 修改 sortPriorityFields 的计算逻辑
  const sortPriorityFields = useMemo(() => {
    // 收集所有字段
    const allFields = [
      ...categoryDimensions.map(d => ({ ...d, section: 'category' as const })),
      ...stackDimensions.map(d => ({ ...d, section: 'stack' as const })),
      ...valueDimensions.map(d => ({ ...d, section: 'value' as const }))
    ]

    // 去重
    const uniqueFields = new Map()
    allFields.forEach(field => {
      if (!uniqueFields.has(field.fieldId)) {
        uniqueFields.set(field.fieldId, field)
      }
    })

    const uniqueFieldsArray = Array.from(uniqueFields.values())

    // 按照 sortPriorityOrder 排序
    return uniqueFieldsArray.sort((a, b) => {
      const indexA = sortPriorityOrder.indexOf(a.id)
      const indexB = sortPriorityOrder.indexOf(b.id)

      // 如果都不在排序列表中，保持原顺序
      if (indexA === -1 && indexB === -1) return 0
      if (indexA === -1) return 1  // a不在列表中，放到后面
      if (indexB === -1) return -1 // b不在列表中，a放到前面

      return indexA - indexB  // 按照排序列表的顺序
    })
  }, [categoryDimensions, stackDimensions, valueDimensions, sortPriorityOrder]) // 添加 sortPriorityOrder 依赖

  const invalidFieldIds = useMemo(() => {
    const validSet = new Set(datasetFields.map(f => f.fieldCode))
    return new Set(
      [...categoryDimensions, ...stackDimensions, ...valueDimensions]
        .filter(d => !validSet.has(d.fieldId))
        .map(d => d.id)
    )
  }, [datasetFields, categoryDimensions, stackDimensions, valueDimensions])

  const handleDropSortPriority = (targetField: any) => {
    if (!draggingId || draggingId === targetField.id) return

    const sourceIndex = sortPriorityOrder.indexOf(draggingId)
    const targetIndex = sortPriorityOrder.indexOf(targetField.id)

    if (sourceIndex === -1 || targetIndex === -1) return

    // 重新排序 sortPriorityOrder
    const newOrder = [...sortPriorityOrder]
    const [moved] = newOrder.splice(sourceIndex, 1)
    newOrder.splice(targetIndex, 0, moved)

    setSortPriorityOrder(newOrder)
    setDraggingId(null)
  }
  // 更新图表
  const handleUpdateChart = () => {
    if (!editingComponent) return

    const dataConfig: DataConfig = {
      dimensions: categoryDimensions.map(dim => ({
        fieldId: dim.fieldId,
        fieldName: dim.originalName,
        fieldCode: dim.name,
        displayName: dim.displayName,
        sort: dim.sort === 'none' ? null : dim.sort,
        timeGranularity: ''
      })),
      metrics: valueDimensions.map(metric => ({
        fieldId: metric.fieldId,
        fieldName: metric.originalName,
        fieldCode: metric.name,
        displayName: metric.displayName,
        sort: metric.sort === 'none' ? null : metric.sort,
        isVirtual: false,
        aggregation: metric.aggregation || 'sum',
        numberFormat: { type: 'number' as const, decimalPlaces: 2, unit: undefined, suffix: undefined, thousandSeparator: true }
      })),
      fieldOrder: [
        ...categoryDimensions.map(d => ({ fieldId: d.fieldId, fieldType: 'dimension' as const })),
        ...valueDimensions.map(m => ({ fieldId: m.fieldId, fieldType: 'metric' as const }))
      ],
      filters: filterGroup ? filterGroup.conditions.map((condition, index) => ({
        id: condition.id || `filter_${Date.now()}_${index}`,
        fieldId: condition.fieldCode || '',
        fieldName: condition.fieldCode || '',
        filterType: condition.fieldType || 'string',
        operator: condition.operator || 'eq',
        value: condition.value || ''
      })) : [],
      timeFilter: startDate || endDate ? {
        type: 'custom' as const,
        startDate: startDate ? new Date(startDate).getTime() : undefined,
        endDate: endDate ? new Date(endDate).getTime() : undefined
      } : undefined,
      resultLimit: {
        limitType: limitType === "limit" ? "limited" as const : "all" as const,
        ...(limitType === "limit" && { limit: Number(limitValue) })
      }
    }

    updateEditingComponent({
      data_config: dataConfig,
      type: chartType,
      title: title,
      style_config: styleConfig,
      dataset_code: editingComponent.dataset_code,
      updated_at: Date.now().toString()
    })

    // 刷新当前图表数据
    refreshChart(editingComponent.id)
  }

  // 公共组件函数
  const PanelHeader = ({ title, onCollapse, icon }: any) => (
    <div className="px-4 py-3 border-b flex items-center justify-between bg-muted/20">
      <h3 className="text-base font-semibold">{title}</h3>
      <Button variant="ghost" size="icon" onClick={onCollapse} className="h-8 w-8">
        {icon}
      </Button>
    </div>
  )

  const CollapseLabel = ({ label, onClick, icon }: any) => (
    <div className="h-full flex flex-col items-center justify-center cursor-pointer hover:bg-accent/50 transition-colors" onClick={onClick}>
      <div className="writing-mode-vertical text-sm font-medium py-4">{label}</div>
      <div className="mt-2">{icon}</div>
    </div>
  )

  const Tab = ({ active, children, onClick }: any) => (
    <div className={`pb-2 cursor-pointer transition-colors ${active ? "border-b-2 border-primary text-primary font-medium" : "text-muted-foreground hover:text-foreground"}`} onClick={onClick}>
      {children}
    </div>
  )

  const FormBlock = ({ label, required, children }: any) => (
    <div className="space-y-2">
      <label className="text-sm font-medium flex items-center gap-1">
        {required && <span className="text-red-500">*</span>}
        {label}
      </label>
      {children}
    </div>
  )

  const CollapsibleBlock = ({ title, required, collapsed, onCollapse, children }: any) => (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium flex items-center gap-1 text-black">
          {required && <span className="text-red-500">*</span>}
          {title}
        </label>
      </div>
      {!collapsed && children}
    </div>
  )

  if (!editingComponent) {
    return (
      <DashboardConfigPanel
        collapsed={configCollapsed.basic}
        onCollapse={() => toggleCollapse('basic')}
      />
    )
  }

  return (
    <div className="fixed right-0 top-14 bottom-0 flex bg-background border-l border-border">

      {false ? (
        <ChartSelector
          charts={[
            { id: '1', name: '堆叠条形图-图表名称', dataset: '会话500-数据集' },
            { id: '2', name: '堆叠条形图-图表名称', dataset: '会话500-数据集' },
            { id: '3', name: '堆叠条形图-图表名称', dataset: '会话500-数据集' },
          ]}
          onSave={(selected, start, end) => console.log(selected, start, end)}
          onCancel={() => console.log('取消')}
        />
      ) : (
        <>
          <div className={`border-r flex flex-col h-full transition-all duration-300 ${configCollapsed.basic ? "w-12" : "w-[400px]"} shrink-0`}>
            {configCollapsed.basic ? (
              <CollapseLabel
                label="基础配置"
                onClick={() => toggleCollapse('basic')}
                icon={<ChevronRight />}
              />
            ) : (
              <div className="flex-1 flex flex-col overflow-hidden">
                <PanelHeader
                  title="基础配置"
                  onCollapse={() => toggleCollapse('basic')}
                  icon={<ChevronLeft />}
                />

                <div className="flex-1 overflow-y-auto px-4 pb-6 pt-4 space-y-6">
                  {/* Tabs */}
                  <div className="flex gap-6 border-b text-sm">
                    <Tab active={configTab === "basic"} onClick={() => setConfigTab("basic")}>
                      基础配置
                    </Tab>
                    <Tab active={configTab === "style"} onClick={() => setConfigTab("style")}>
                      自定义样式
                    </Tab>
                  </div>

                  {configTab === "basic" ? (
                    <>
                      {/* 图表类型 */}
                      <FormBlock label="图表类型" required>
                        <Select
                          value={chartType}
                          onValueChange={(value: ChartType) => {
                            setChartType(value)
                            const selectedChart = CHART_TYPES.find(item => item.value === value)
                            setTitle(selectedChart?.label || '')
                          }}
                        >
                          <SelectTrigger className="w-full h-9">
                            <SelectValue placeholder="选择图表类型">
                              {CHART_TYPES.find(item => item.value === chartType)?.label || '选择图表类型'}
                            </SelectValue>
                          </SelectTrigger>
                          <SelectContent>
                            {CHART_TYPES.map((item) => (
                              <SelectItem key={item.value} value={item.value}>
                                {item.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </FormBlock>

                      {/* 类别轴 / 维度 */}
                      <CollapsibleBlock
                        title="类别轴 / 维度"
                        required
                        collapsed={configCollapsed.category}
                        onCollapse={() => toggleCollapse('category')}
                      >
                        <DimensionBlock
                          invalidIds={invalidFieldIds}
                          isDimension={true}
                          dimensions={categoryDimensions}
                          maxDimensions={2}
                          isDragOver={dragOverSection === 'category'}
                          onDragOver={(e) => handleDragOver(e, 'category')}
                          onDragLeave={handleDragLeave}
                          onDrop={(e) => handleDrop(e, 'category')}
                          onDelete={(dimensionId) => handleDeleteDimension('category', dimensionId)}
                          onSortChange={(dimensionId, sortValue) => handleSortChange('category', dimensionId, sortValue)}
                          onEditDisplayName={(dimensionId, originalName, displayName) =>
                            openEditDialog('category', dimensionId, originalName, displayName)
                          }
                        />
                      </CollapsibleBlock>

                      {/* 堆叠项 / 维度 */}
                      <CollapsibleBlock
                        title="堆叠项 / 维度"
                        collapsed={configCollapsed.stack}
                        onCollapse={() => toggleCollapse('stack')}
                      >
                        <DimensionBlock
                          invalidIds={invalidFieldIds}
                          isDimension={true}
                          dimensions={stackDimensions}
                          isDragOver={dragOverSection === 'stack'}
                          onDragOver={(e) => handleDragOver(e, 'stack')}
                          onDragLeave={handleDragLeave}
                          onDrop={(e) => handleDrop(e, 'stack')}
                          onDelete={(dimensionId) => handleDeleteDimension('stack', dimensionId)}
                          onSortChange={(dimensionId, sortValue) => handleSortChange('stack', dimensionId, sortValue)}
                          onEditDisplayName={(dimensionId, originalName, displayName) =>
                            openEditDialog('stack', dimensionId, originalName, displayName)
                          }
                        />
                      </CollapsibleBlock>

                      {/* 值轴 / 指标 */}
                      <CollapsibleBlock
                        title="值轴 / 指标"
                        required
                        collapsed={configCollapsed.value}
                        onCollapse={() => toggleCollapse('value')}
                      >
                        <DimensionBlock
                          invalidIds={invalidFieldIds}
                          isDimension={false}
                          dimensions={valueDimensions}
                          isDragOver={dragOverSection === 'value'}
                          onDragOver={(e) => handleDragOver(e, 'value')}
                          onDragLeave={handleDragLeave}
                          onDrop={(e) => handleDrop(e, 'value')}
                          onDelete={(dimensionId) => handleDeleteDimension('value', dimensionId)}
                          onSortChange={(dimensionId, sortValue) => handleSortChange('value', dimensionId, sortValue)}
                          onEditDisplayName={(dimensionId, originalName, displayName) =>
                            openEditDialog('value', dimensionId, originalName, displayName)
                          }
                        />
                      </CollapsibleBlock>

                      {/* 排序优先级 */}
                      <CollapsibleBlock title="排序优先级">
                        <div className="space-y-2">
                          {sortPriorityFields.length === 0 ? (
                            <div className="text-xs text-muted-foreground text-center py-2">
                              添加维度或指标后可调整排序优先级
                            </div>
                          ) : (
                            sortPriorityFields.map((field) => (
                              <div
                                key={field.id}
                                draggable
                                onMouseDown={() => setDraggingId(field.id)}
                                onDragStart={(e) => {
                                  setDraggingId(field.id)
                                  e.dataTransfer.effectAllowed = 'move'
                                  e.dataTransfer.setData('text/plain', field.id)
                                }}
                                onDragOver={(e) => e.preventDefault()}
                                onDrop={(e) => {
                                  e.preventDefault()
                                  const sourceId = e.dataTransfer.getData('text/plain')
                                  if (!sourceId) return
                                  setDraggingId(sourceId)
                                  handleDropSortPriority(field)
                                }}
                                className={`flex items-center gap-2 px-3 py-2 border rounded-md bg-muted/20 ${draggingId === field.id ? 'opacity-50' : ''}`}
                              >
                                <GripVertical className="h-4 w-4 text-muted-foreground cursor-grab" />
                                <span className="text-sm truncate">{field.displayName}</span>
                              </div>
                            ))
                          )}
                        </div>

                      </CollapsibleBlock>

                      {/* 筛选 */}
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <label className="text-sm font-medium">筛选</label>
                        </div>

                        {!filterGroup || filterGroup.conditions.length === 0 ? (
                          <div className="text-sm text-muted-foreground text-center py-1 border rounded bg-muted/20">
                            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={handleAddFilter}>
                              <Plus className="h-3 w-3 mr-1" />添加筛选条件
                            </Button>
                          </div>
                        ) : (
                          <div className="space-y-2 bg-blue-100 rounded-md border-blue-300">
                            <div className="flex items-center justify-between p-2 border rounded-md bg-muted/20 hover:bg-muted/40">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-blue-700">
                                  已添加 {filterGroup.conditions.length} 个筛选条件
                                  {filterGroup.conditions.length > 1 && ` (${filterGroup.logic?.toUpperCase() || 'AND'})`}
                                </span>
                              </div>
                              <div className="flex items-center gap-1">
                                <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleEditFilter}>
                                  <ChevronDown className="h-3 w-3" />
                                </Button>
                                <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleDeleteFilter}>
                                  <X className="h-3 w-3" />
                                </Button>
                              </div>
                            </div>

                          </div>
                        )}
                      </div>

                      {/* 时间范围 */}
                      <FormBlock label="时间范围">
                        <TimeRangePicker
                          startDate={startDate}
                          endDate={endDate}
                          onChange={(range) => {
                            setStartDate(range.startDate || '')
                            setEndDate(range.endDate || '')
                          }}
                        />
                      </FormBlock>

                      {/* 结果显示 */}
                      <FormBlock label="结果显示">
                        <div className="flex items-center gap-4">
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input type="radio" checked={limitType === "all"} onChange={() => setLimitType("all")} className="h-4 w-4" />
                            <span className="text-sm">全部</span>
                          </label>
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input type="radio" checked={limitType === "limit"} onChange={() => setLimitType("limit")} className="h-4 w-4" />
                            <Input className="w-20 h-8" value={limitValue} disabled={limitType !== "limit"} onChange={(e) => setLimitValue(e.target.value)} />
                            <span className="text-sm text-muted-foreground">条</span>
                          </label>
                        </div>
                      </FormBlock>

                      <Button className="w-full h-10 mt-4" onClick={handleUpdateChart}>更新图表数据</Button>
                    </>
                  ) : (
                    <StyleConfigPanel config={styleConfig} onChange={setStyleConfig} />
                  )}
                </div>
              </div>
            )}
          </div>
          <div className={`flex flex-col h-full transition-all duration-300 ${configCollapsed.data ? "w-12 shrink-0" : "w-[400px]"}`}>
            {configCollapsed.data ? (
              <CollapseLabel label="数据集配置" onClick={() => toggleCollapse('data')} icon={<ChevronLeft />} />
            ) : (
              <div className="flex-1 flex flex-col overflow-hidden">
                <PanelHeader title="数据集配置" onCollapse={() => toggleCollapse('data')} icon={<ChevronRight />} />
                <div className="flex-1 overflow-auto">
                  <DatasetSelector
                    selectedDatasetCode={editingComponent.dataset_code}
                    onDatasetChange={handleDatasetChange}
                    onDragStart={handleDragStart}
                    onFieldsLoaded={setDatasetFields}
                  />

                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* 编辑显示名称弹窗 */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader><DialogTitle>编辑显示名称</DialogTitle></DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <div className="text-sm text-muted-foreground mb-1">原始名称</div>
              <div className="text-sm font-medium px-2 py-1 bg-muted rounded">{editingDimension?.originalName}</div>
            </div>
            <div>
              <div className="text-sm font-medium mb-1">显示名称 *</div>
              <Input
                value={editingDimension?.displayName || ''}
                onChange={(e) => setEditingDimension(prev => prev ? { ...prev, displayName: e.target.value } : null)}
                placeholder="请输入显示名称"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditDialogOpen(false)}>取消</Button>
            <Button onClick={saveDisplayName}>确认</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 筛选条件弹窗 */}

      <FilterConditionDialog
        open={filterDialogOpen}
        onOpenChange={setFilterDialogOpen}
        value={filterGroup}
        onChange={handleSaveFilter}
        fields={datasetFields}
      />
    </div>
  )
}