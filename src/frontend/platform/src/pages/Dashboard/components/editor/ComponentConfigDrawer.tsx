"use client"

import { useState, useEffect, useMemo } from "react"
import { ChevronLeft, ChevronRight, GripVertical, Plus, X, ChevronDown } from "lucide-react"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/bs-ui/dialog"

import { ChartType, ComponentStyleConfig, DashboardComponent, DataConfig } from "../../types/dataConfig"
import { DatasetSelector } from "./DatasetSelector"
import { StyleConfigPanel } from "./StyleConfigPanel"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { DimensionBlock } from "./DimensionBlock"

// 图表类型选项
const CHART_TYPES = [
  { label: "基础柱状图", value: "bar" },
  { label: "堆叠柱状图", value: "stacked-bar" },
  { label: "分组柱状图", value: "grouped-bar" },
  { label: "基础条形图", value: "horizontal-bar" },
  { label: "堆叠条形图", value: "stacked-horizontal-bar" },
  { label: "分组条形图", value: "grouped-horizontal-bar" },
  { label: "基础折线图", value: "line" },
  { label: "面积图", value: "area" },
  { label: "堆叠折线图", value: "stacked-line" },
  { label: "饼状图", value: "pie" },
  { label: "环状图", value: "donut" },
  { label: "指标卡", value: "metric" },
  { label: "查询组件", value: "query" }
]

interface ComponentConfigDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  component: DashboardComponent | null
}

export function ComponentConfigDrawer({
  open,
  onOpenChange,  
  component
}: ComponentConfigDrawerProps) {
  if (!open || !component) return null

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
  const [chartType, setChartType] = useState<ChartType>(component.type || 'bar')
  const [title, setTitle] = useState(component.title || '')
  const [limitType, setLimitType] = useState<"all" | "limit">("limit")
  const [limitValue, setLimitValue] = useState("1000")
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const updateComponent = useEditorDashboardStore(state => state.updateComponent)

  // 维度数据状态
  const [categoryDimensions, setCategoryDimensions] = useState<any[]>([])
  const [stackDimensions, setStackDimensions] = useState<any[]>([])
  const [valueDimensions, setValueDimensions] = useState<any[]>([])
  const [filters, setFilters] = useState<any[]>([])
  const [dragOverSection, setDragOverSection] = useState<string | null>(null)

  // 对话框状态
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)
  const [editingDimension, setEditingDimension] = useState<any>(null)
  const [editingFilter, setEditingFilter] = useState<any>({ fieldName: '', operator: 'eq', value: '' })

  // 初始化
  useEffect(() => {
    if (component) {
      setChartType(component.type)
      setStyleConfig(component.style_config)
    }
  }, [component.type])

  // 数据集改变
  const handleDatasetChange = (datasetCode: string) => {
    if (component) {
      updateComponent(component.id, { dataset_code: datasetCode })
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
        const fieldType = data.fieldType || 'dimension'
        
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
    setEditingFilter({ fieldName: '', operator: 'eq', value: '' })
    setFilterDialogOpen(true)
  }

  const handleEditFilter = (filter: any) => {
    setEditingFilter(filter)
    setFilterDialogOpen(true)
  }

  const handleDeleteFilter = (filterId: string) => {
    setFilters(prev => prev.filter(f => f.id !== filterId))
  }

  const handleSaveFilter = () => {
    if (!editingFilter.fieldName || !editingFilter.value) return

    if (editingFilter.id) {
      setFilters(prev => prev.map(f => f.id === editingFilter.id ? editingFilter : f))
    } else {
      setFilters(prev => [...prev, { ...editingFilter, id: `filter_${Date.now()}` }])
    }
    setFilterDialogOpen(false)
    setEditingFilter({ fieldName: '', operator: 'eq', value: '' })
  }

  // 切换折叠
  const toggleCollapse = (section: keyof typeof configCollapsed) => {
    setConfigCollapsed(prev => ({ ...prev, [section]: !prev[section] }))
  }

  // 排序优先级字段
  const sortPriorityFields = useMemo(() => {
    return [
      ...categoryDimensions.map(d => ({ ...d, section: 'category' as const })),
      ...stackDimensions.map(d => ({ ...d, section: 'stack' as const })),
      ...valueDimensions.map(d => ({ ...d, section: 'value' as const }))
    ]
  }, [categoryDimensions, stackDimensions, valueDimensions])

  // 更新图表
  const handleUpdateChart = () => {
    if (!component) return

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
      filters: filters.map(filter => ({
        id: filter.id,
        fieldId: filter.fieldName,
        fieldName: filter.fieldName,
        filterType: 'string',
        operator: filter.operator,
        value: filter.value
      })),
      resultLimit: {
        limitType: limitType === "limit" ? "limited" as const : "all" as const,
        ...(limitType === "limit" && { limit: Number(limitValue) })
      }
    }

    updateComponent(component.id, {
      data_config: dataConfig,
      type: chartType,
      title: title,
      style_config: styleConfig,
      updated_at: Date.now().toString()
    })
  }

  // 公共组件函数（保持简单）
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

  return (
    <div className="fixed right-0 top-14 bottom-0 flex bg-background border-l border-border">
      {/* 左侧基础配置模块 */}
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
                            onDragStart={() => setDraggingId(field.id)}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={() => {
                              if (!draggingId || draggingId === field.id) return

                              const sourceIndex = sortPriorityFields.findIndex(f => f.id === draggingId)
                              const targetIndex = sortPriorityFields.findIndex(f => f.id === field.id)
                              if (sourceIndex === -1 || targetIndex === -1) return

                              const newList = [...sortPriorityFields]
                              const [moved] = newList.splice(sourceIndex, 1)
                              newList.splice(targetIndex, 0, moved)

                              const newCategory = newList.filter(f => f.section === 'category')
                              const newStack = newList.filter(f => f.section === 'stack')
                              const newValue = newList.filter(f => f.section === 'value')

                              setCategoryDimensions(newCategory)
                              setStackDimensions(newStack)
                              setValueDimensions(newValue)
                              setDraggingId(null)
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
                    
                    {filters.length === 0 ? (
                      <div className="text-sm text-muted-foreground text-center py-1 border rounded bg-muted/20">
                        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={handleAddFilter}>
                          <Plus className="h-3 w-3 mr-1" />添加筛选条件
                        </Button>
                      </div>
                    ) : (
                      <div className="space-y-2 bg-blue-100 rounded-md border-blue-300">
                        {filters.map((filter) => (
                          <div key={filter.id} className="flex items-center justify-between p-2 border rounded-md bg-muted/20 hover:bg-muted/40">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-blue-700">已添加筛选条件</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => handleEditFilter(filter)}>
                                <ChevronDown className="h-3 w-3" />
                              </Button>
                              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => handleDeleteFilter(filter.id)}>
                                <X className="h-3 w-3" />
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* 时间范围 */}
                  <FormBlock label="时间范围">
                    <div className="flex items-center gap-2">
                      <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-9" />
                      <span className="text-muted-foreground text-sm">至</span>
                      <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-9" />
                    </div>
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

      {/* 右侧数据集配置模块 */}
      <div className={`flex flex-col h-full transition-all duration-300 ${configCollapsed.data ? "w-12 shrink-0" : "w-[400px]"}`}>
        {configCollapsed.data ? (
          <CollapseLabel label="数据集配置" onClick={() => toggleCollapse('data')} icon={<ChevronLeft />} />
        ) : (
          <div className="flex-1 flex flex-col overflow-hidden">
            <PanelHeader title="数据集配置" onCollapse={() => toggleCollapse('data')} icon={<ChevronRight />} />
            <div className="flex-1 overflow-auto">
              <DatasetSelector
                selectedDatasetCode={component.dataset_code}
                onDatasetChange={handleDatasetChange}
                onDragStart={handleDragStart}
              />
            </div>
          </div>
        )}
      </div>

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
      <Dialog open={filterDialogOpen} onOpenChange={setFilterDialogOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>{editingFilter.id ? '编辑筛选条件' : '添加筛选条件'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">字段名称</label>
              <Input value={editingFilter.fieldName} onChange={(e) => setEditingFilter(prev => ({ ...prev, fieldName: e.target.value }))} placeholder="请输入字段名称" />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">操作符</label>
              <Select value={editingFilter.operator} onValueChange={(value) => setEditingFilter(prev => ({ ...prev, operator: value }))}>
                <SelectTrigger><SelectValue placeholder="选择操作符" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="eq">等于 (=)</SelectItem>
                  <SelectItem value="neq">不等于 (!=)</SelectItem>
                  <SelectItem value="gt">大于 ({">"})</SelectItem>
                  <SelectItem value="gte">大于等于 ({">"}=)</SelectItem>
                  <SelectItem value="lt">小于 ({"<"})</SelectItem>
                  <SelectItem value="lte">小于等于 ({"<="})</SelectItem>
                  <SelectItem value="contains">包含</SelectItem>
                  <SelectItem value="not_contains">不包含</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">值</label>
              <Input value={editingFilter.value} onChange={(e) => setEditingFilter(prev => ({ ...prev, value: e.target.value }))} placeholder="请输入值" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFilterDialogOpen(false)}>取消</Button>
            <Button onClick={handleSaveFilter} disabled={!editingFilter.fieldName || !editingFilter.value}>
              {editingFilter.id ? '更新' : '添加'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}