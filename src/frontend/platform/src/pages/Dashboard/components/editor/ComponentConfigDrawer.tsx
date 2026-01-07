// ComponentConfigDrawer.tsx
"use client"

import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { ChevronDown, ChevronLeft, ChevronRight, GripVertical, Plus, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { ChartType, ComponentStyleConfig, DataConfig } from "../../types/dataConfig"
import { DatasetField, DatasetSelector } from "./DatasetSelector"
import { StyleConfigPanel } from "./StyleConfigPanel"
import { DimensionBlock } from "./DimensionBlock"
import { FilterConditionDialog } from "./FilterConditionDialog"
import ChartSelector from "./ChartSelector"
import { DashboardConfigPanel } from "./DashboardConfigPanel"
import { AdvancedDatePicker } from "../AdvancedDatePicker"
import { useChartState } from "./useChartState"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import ComponentPicker, { ChartGroupItems, ChartItems } from "./ComponentPicker"

// 图表类型选项
export const CHART_TYPES: {
  label: string;
  value: ChartType;
  hasStack: boolean; // 是否有堆叠项维度
}[] = [
    { label: "基础柱状图", value: ChartType.Bar, hasStack: false },
    { label: "堆叠柱状图", value: ChartType.StackedBar, hasStack: true },
    { label: "组合柱状图", value: ChartType.GroupedBar, hasStack: false },

    { label: "基础条形图", value: ChartType.HorizontalBar, hasStack: false },
    { label: "堆叠条形图", value: ChartType.StackedHorizontalBar, hasStack: true },
    { label: "组合条形图", value: ChartType.GroupedHorizontalBar, hasStack: false },

    { label: "分组条形图", value: ChartType.GroupedHorizontalBar, hasStack: false },

    { label: "基础折线图", value: ChartType.Line, hasStack: false },
    { label: "堆叠折线图", value: ChartType.StackedLine, hasStack: true },
    { label: "基础面积图", value: ChartType.Area, hasStack: false },
    { label: "堆叠面积图", value: ChartType.StackedArea, hasStack: true },

    { label: "饼状图", value: ChartType.Pie, hasStack: false },
    { label: "环状图", value: ChartType.Donut, hasStack: false },

    { label: "指标卡", value: ChartType.Metric, hasStack: false },
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
  const { toast } = useToast()

  // Tab状态
  const [configTab, setConfigTab] = useState<"basic" | "style">("basic")

  // 限制结果状态
  const [limitType, setLimitType] = useState<"all" | "limit">("limit")
  const [limitValue, setLimitValue] = useState("1000")

  // 数据集字段
  const [datasetFields, setDatasetFields] = useState<DatasetField[]>([])

  // 对话框状态
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)
  const [editingDimension, setEditingDimension] = useState<any>(null)

  // 使用自定义Hook管理所有图表状态
  const chartState = useChartState(editingComponent)

  // 从Hook中解构状态和方法
  const {
    chartType,
    title,
    styleConfig,
    categoryDimensions,
    stackDimensions,
    valueDimensions,
    dragOverSection,
    filterGroup,
    draggingId,
    sortPriorityFields,
    currentChartHasStack,
    handleChartTypeChange,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleDeleteDimension,
    handleSortChange,
    handleDropSortPriority,
    handleAddFilter,
    handleDeleteFilter,
    setDraggingId,
    setFilterGroup,
    getDataConfig
  } = chartState
  const handleFieldClick = useCallback((field: DatasetField) => {
    if (!editingComponent) return

    const safeFieldId = field.fieldId || field.fieldCode || field.fieldName;

    const isFieldAlreadyAdded = (fieldId: string, section: 'category' | 'stack' | 'value'): boolean => {
      switch (section) {
        case 'category':
          return categoryDimensions.some(dim => dim.fieldId === fieldId)
        case 'stack':
          return stackDimensions.some(dim => dim.fieldId === fieldId)
        case 'value':
          return valueDimensions.some(dim => dim.fieldId === fieldId)
        default:
          return false
      }
    }

    if (field.role === 'dimension') {
      if (categoryDimensions.length < 2) {
        if (isFieldAlreadyAdded(safeFieldId, 'category')) {
          toast({ description: "字段已存在于类别轴中", variant: "warning" })
          return
        }
        const newDimension = {
          id: `${safeFieldId}-${Date.now()}`,
          fieldId: safeFieldId,
          displayName: field.displayName || field.fieldName,
          originalName: field.displayName || field.fieldName,
          fieldType: field.role,
          sort: null
        }
        chartState.setCategoryDimensions(prev => [...prev, newDimension])
      } else if (currentChartHasStack && stackDimensions.length === 0) {
        if (isFieldAlreadyAdded(safeFieldId, 'stack')) {
          toast({ description: "字段已存在于堆叠项中", variant: "warning" })
          return
        }
        const newDimension = {
          id: `${safeFieldId}-${Date.now()}`,
          fieldId: safeFieldId,
          displayName: field.displayName || field.fieldName,
          originalName: field.displayName || field.fieldName,
          fieldType: field.role,
          sort: null
        }
        chartState.setStackDimensions(prev => [...prev, newDimension])
      } else {
        toast({ description: "当前维度数量已达到上限", variant: "warning" })
      }
    } else if (field.role === 'metric') {
      if (isFieldAlreadyAdded(safeFieldId, 'value')) {
        toast({ description: "字段已存在于指标区域中", variant: "warning" })
        return
      }
      const newMetric = {
        id: `${safeFieldId}-${Date.now()}`,
        fieldId: safeFieldId,
        displayName: field.displayName || field.fieldName,
        originalName: field.displayName || field.fieldName,
        fieldType: field.role,
        sort: null,
        aggregation: 'sum' as const
      }
      chartState.setValueDimensions(prev => [...prev, newMetric])
    }
  }, [editingComponent, categoryDimensions, stackDimensions, valueDimensions, currentChartHasStack, chartState, toast])
  const invalidFieldIds = useMemo(() => {
    const validSet = new Set(
      datasetFields.map(f => f.fieldId || f.fieldCode || f.fieldName).filter(Boolean)
    )

    return new Set(
      [...categoryDimensions, ...stackDimensions, ...valueDimensions]
        .filter(d => !validSet.has(d.fieldId))
        .map(d => d.id)
    )
  }, [datasetFields, categoryDimensions, stackDimensions, valueDimensions])



  // 数据集改变
  const handleDatasetChange = useCallback((datasetCode: string) => {
    if (editingComponent) {
      updateEditingComponent({ dataset_code: datasetCode })
    }
  }, [editingComponent, updateEditingComponent])

  // 拖拽开始
  const handleDragStart = useCallback((e: React.DragEvent, data: any) => {
    e.dataTransfer.setData('application/json', JSON.stringify(data))
  }, [])

  // 编辑显示名称
  const openEditDialog = useCallback((section: 'category' | 'stack' | 'value', dimensionId: string, originalName: string, displayName: string) => {
    setEditingDimension({ id: dimensionId, section, originalName, displayName })
    setEditDialogOpen(true)
  }, [])

  const saveDisplayName = useCallback(() => {
    if (editingDimension) {
      // 更新对应的维度显示名称
      const updateDimensions = (prev: any[]) =>
        prev.map(d => d.id === editingDimension.id ? { ...d, displayName: editingDimension.displayName } : d)

      if (editingDimension.section === 'category') {
        chartState.setCategoryDimensions(updateDimensions(chartState.categoryDimensions))
      } else if (editingDimension.section === 'stack') {
        chartState.setStackDimensions(updateDimensions(chartState.stackDimensions))
      } else if (editingDimension.section === 'value') {
        chartState.setValueDimensions(updateDimensions(chartState.valueDimensions))
      }

      setEditDialogOpen(false)
      setEditingDimension(null)
    }
  }, [editingDimension, chartState])

  // 筛选条件
  const handleEditFilter = useCallback(() => {
    if (filterGroup) {
      setFilterDialogOpen(true)
    } else {
      handleAddFilter()
      setFilterDialogOpen(true)
    }
  }, [filterGroup, handleAddFilter])

  const handleSaveFilter = useCallback((newFilterGroup: any) => {
    setFilterGroup(newFilterGroup)
    setFilterDialogOpen(false)
  }, [])

  // 切换折叠
  const toggleCollapse = useCallback((section: keyof typeof configCollapsed) => {
    setConfigCollapsed(prev => ({ ...prev, [section]: !prev[section] }))
  }, [])

  // 更新图表
  const handleUpdateChart = useCallback(() => {
    if (!editingComponent) return

    const dataConfig = getDataConfig(limitType, limitValue, editingComponent.data_config?.timeFilter)

    updateEditingComponent({
      data_config: dataConfig,
      type: chartType,
      title: title,
      style_config: styleConfig,
      dataset_code: editingComponent.dataset_code
    })

    // 刷新当前图表数据
    refreshChart(editingComponent.id)
  }, [editingComponent, chartType, title, styleConfig, limitType, limitValue, getDataConfig, updateEditingComponent, refreshChart])

  // 时间范围改变
  const handleTimeFilterChange = useCallback((val: any) => {
    console.log("Day Range Change:", val);
    if (editingComponent) {
      // 只更新 timeFilter，避免触发整个组件的重新初始化
      updateEditingComponent({
        ...editingComponent,
        data_config: {
          ...editingComponent.data_config,
          timeFilter: val ? {
            type: 'custom' as const,
            startDate: val.startTime * 1000,
            endDate: val.endTime * 1000
          } : undefined
        }
      });
    }
  }, [editingComponent, updateEditingComponent])

  // 公共组件函数
  const PanelHeader = useCallback(({ title: panelTitle, onCollapse, icon }: any) => (
    <div className="px-4 py-3 border-b flex items-center justify-between bg-muted/20">
      <h3 className="text-base font-semibold">{panelTitle}</h3>
      <Button variant="ghost" size="icon" onClick={onCollapse} className="h-8 w-8">
        {icon}
      </Button>
    </div>
  ), [])

  const CollapseLabel = useCallback(({ label, onClick, icon }: any) => (
    <div className="h-full flex flex-col items-center justify-center cursor-pointer hover:bg-accent/50 transition-colors" onClick={onClick}>
      <div className="writing-mode-vertical text-sm font-medium py-4">{label}</div>
      <div className="mt-2">{icon}</div>
    </div>
  ), [])

  const Tab = useCallback(({ active, children, onClick }: any) => (
    <div className={`pb-2 cursor-pointer transition-colors ${active ? "border-b-2 border-primary text-primary font-medium" : "text-muted-foreground hover:text-foreground"}`} onClick={onClick}>
      {children}
    </div>
  ), [])

  const FormBlock = useCallback(({ label, required, children }: any) => (
    <div className="space-y-2">
      <label className="text-sm font-medium flex items-center gap-1">
        {required && <span className="text-red-500">*</span>}
        {label}
      </label>
      {children}
    </div>
  ), [])

  const CollapsibleBlock = useCallback(({ title: blockTitle, required, collapsed, onCollapse, children }: any) => (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium flex items-center gap-1 text-black">
          {required && <span className="text-red-500">*</span>}
          {blockTitle}
        </label>
      </div>
      {!collapsed && children}
    </div>
  ), [])

  if (!editingComponent) {
    return (
      <DashboardConfigPanel
        collapsed={configCollapsed.basic}
        onCollapse={() => toggleCollapse('basic')}
      />
    )
  }

  return (
    <div className="h-full flex bg-background border-l border-border">
      {editingComponent.type === 'query' ? (
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
          <div className={`border-r flex flex-col h-full transition-all duration-300 ${configCollapsed.basic ? "w-12" : "w-[300px]"} shrink-0`}>
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
                      {
                        editingComponent.type !== 'metric' && (
                          <>
                            {/* 图表类型 */}
                            <FormBlock label="图表类型" required>
                              <ComponentPicker onSelect={(data) => handleChartTypeChange(data.type)} maxHeight={500}>
                                <div className="relative w-full group">
                                  <div className="flex h-9 w-full items-center justify-between rounded-md border border-gray-300 bg-white px-3 py-2 text-sm transition-colors hover:border-gray-400 cursor-pointer">
                                    {/* 文本区域 */}
                                    <div className="flex-1">
                                      <span className="truncate text-gray-700">
                                        {ChartGroupItems
                                          .flatMap(item => item.data)
                                          .find(item => item.type === chartType)?.label || '选择图表类型'}
                                      </span>
                                    </div>
                                    {/* ChevronDown 图标 */}
                                    <ChevronDown className="h-4 w-4 text-gray-500 flex-shrink-0" />
                                  </div>
                                </div>
                              </ComponentPicker>
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
                            {currentChartHasStack && (
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
                            )}
                          </>
                        )
                      }


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
                      {editingComponent.type !== 'metric' && <CollapsibleBlock title="排序优先级">
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

                      </CollapsibleBlock>}

                      {/* 筛选 */}
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <label className="text-sm font-medium">筛选</label>
                        </div>

                        {!filterGroup || filterGroup.conditions.length === 0 ? (
                          <div className="text-sm text-muted-foreground text-center py-1 border rounded bg-muted/20">
                            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={handleEditFilter}>
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

                      <FormBlock label="时间范围">
                        <AdvancedDatePicker
                          granularity={'day'}
                          mode={'range'}
                          value={editingComponent?.data_config?.timeFilter ? {
                            startTime: Math.floor(editingComponent.data_config.timeFilter.startDate! / 1000),
                            endTime: Math.floor(editingComponent.data_config.timeFilter.endDate! / 1000),
                            shortcutKey: undefined,
                            isDynamic: false
                          } : undefined}
                          onChange={handleTimeFilterChange}
                          placeholder="选择时间范围"
                        />
                      </FormBlock>

                      {/* 结果显示 */}
                      {editingComponent.type !== 'metric' && <FormBlock label="结果显示">
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
                      </FormBlock>}

                      <Button className="w-full h-10 mt-4" onClick={handleUpdateChart}>更新图表数据</Button>
                    </>
                  ) : (
                    <StyleConfigPanel config={styleConfig} type={editingComponent.type} onChange={chartState.setStyleConfig} />
                  )}
                </div>
              </div>
            )}
          </div>
          <div className={`flex flex-col h-full transition-all duration-300 ${configCollapsed.data ? "w-12 shrink-0" : "w-[300px]"}`}>
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
                    onFieldClick={handleFieldClick}
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