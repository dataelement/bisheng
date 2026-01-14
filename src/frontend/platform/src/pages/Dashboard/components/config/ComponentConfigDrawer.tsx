// ComponentConfigDrawer.tsx
"use client"

import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { ChevronDown, GripVertical, ListIndentDecrease, ListIndentIncrease, X } from "lucide-react"

import { useCallback, useEffect, useMemo, useState } from "react"

import { Label } from "@/components/bs-ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { useTranslation } from "react-i18next"
import { ChartType, QueryConfig } from "../../types/dataConfig"
import { AdvancedDatePicker } from "../AdvancedDatePicker"
import ComponentPicker, { ChartGroupItems } from "../editor/ComponentPicker"
import ChartSelector from "./ChartSelector"
import { DashboardConfigPanel } from "./DashboardConfigPanel"
import { DatasetField, DatasetSelector } from "./DatasetSelector"
import { DimensionBlock } from "./DimensionBlock"
import { FilterConditionDialog } from "./FilterConditionDialog"
import { StyleConfigPanel } from "./StyleConfigPanel"
import { useChartState } from "./useChartState"
import { generateUUID } from "@/components/bs-ui/utils"


export function ComponentConfigDrawer() {
  const { t } = useTranslation("dashboard")
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

  const [filter, setFilter] = useState<any>([])
  // 使用自定义Hook管理所有图表状态
  const chartState = useChartState(editingComponent)
  const [isMetricCard, setIsMetricCard] = useState(true)

  // 从Hook中解构状态和方法
  const {
    chartType,
    title,
    setTitle,
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
  const STACKED_CHART_TYPES = new Set<ChartType>([
    ChartType.StackedBar,
    ChartType.StackedHorizontalBar,
    ChartType.StackedLine
  ])
  const getMaxMetricCount = (chartType: ChartType) => {
    return STACKED_CHART_TYPES.has(chartType) ? 3 : 1
  }
  const isVirtualMetric = (field: DatasetField) => {
    return field.isVirtual === true
  }

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
          toast({
            description: t("componentConfigDrawer.toast.fieldAlreadyExists", {
              section: t("componentConfigDrawer.sections.category")
            }),
            variant: "warning"
          })
          return
        }
        const newDimension = {
          id: `${safeFieldId}-${Date.now()}`,
          fieldId: safeFieldId,
          displayName: field.displayName || field.fieldName,
          originalName: field.displayName || field.fieldName,
          fieldType: field.role,
          timeGranularity: field.timeGranularity,
          sort: null
        }
        chartState.setCategoryDimensions(prev => [...prev, newDimension])
      } else if (currentChartHasStack && stackDimensions.length === 0) {
        if (isFieldAlreadyAdded(safeFieldId, 'stack')) {
          toast({
            description: t("componentConfigDrawer.toast.fieldAlreadyExists", {
              section: t("componentConfigDrawer.sections.stack")
            }),
            variant: "warning"
          })
          return
        }
        const newDimension = {
          id: `${safeFieldId}-${Date.now()}`,
          fieldId: safeFieldId,
          displayName: field.displayName || field.fieldName,
          originalName: field.displayName || field.fieldName,
          fieldType: field.role,
          timeGranularity: field.timeGranularity,
          sort: null
        }
        chartState.setStackDimensions(prev => [...prev, newDimension])
      } else {
        toast({
          description: t("componentConfigDrawer.toast.dimensionLimitReached"),
          variant: "warning"
        })
      }
    } else if (field.role === 'metric') {
      const maxMetricCount = getMaxMetricCount(chartType)
      const hasVirtualMetric = valueDimensions.some(d => d.isVirtual)
      const currentIsVirtual = isVirtualMetric(field)

      if (valueDimensions.length >= maxMetricCount) {
        toast({
          description: t("componentConfigDrawer.toast.metricLimitReached", {
            count: maxMetricCount
          }),
          variant: "warning"
        })
        return
      }

      if (valueDimensions.length > 0) {
        if (currentIsVirtual && !hasVirtualMetric) {
          toast({
            description: t("componentConfigDrawer.toast.virtualMetricConflict"),
            variant: "warning"
          })
          return
        }

        if (!currentIsVirtual && hasVirtualMetric) {
          toast({
            description: t("componentConfigDrawer.toast.virtualMetricConflict"),
            variant: "warning"
          })
          return
        }

        // 多个虚拟指标
        if (currentIsVirtual && hasVirtualMetric) {
          toast({
            description: t("componentConfigDrawer.toast.multipleVirtualMetric"),
            variant: "warning"
          })
          return
        }
      }

      if (isFieldAlreadyAdded(safeFieldId, 'value')) {
        toast({
          description: t("componentConfigDrawer.toast.fieldAlreadyExists", {
            section: t("componentConfigDrawer.sections.value")
          }),
          variant: "warning"
        })
        return
      }

      const newMetric = {
        id: `${safeFieldId}-${Date.now()}`,
        fieldId: safeFieldId,
        displayName: field.displayName || field.fieldName,
        originalName: field.displayName || field.fieldName,
        fieldType: field.role,
        sort: null,
        aggregation: 'sum' as const,
        isVirtual: currentIsVirtual
      }

      chartState.setValueDimensions(prev => [...prev, newMetric])
    }

  }, [editingComponent, categoryDimensions, stackDimensions, valueDimensions, currentChartHasStack, chartState, toast, t])

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
  useEffect(() => {
    if (chartType === 'metric') {
      setIsMetricCard(false)
    } else {
      setIsMetricCard(true)
    }
  }, [chartType])
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

  const handleMetricFormatChange = useCallback(
    (dimensionId: string, format: any) => {
      chartState.setValueDimensions(prev =>
        prev.map(d =>
          d.id === dimensionId
            ? { ...d, numberFormat: format }
            : d
        )
      )
    },
    [chartState]
  )

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
  // 更新图表 - 添加校验
  const handleUpdateChart = useCallback((e) => {
    if (!editingComponent) return

    if (editingComponent.type !== 'query' && editingComponent.type !== 'metric') {
      if (!chartType) {
        toast({
          description: t("componentConfigDrawer.validation.chartTypeRequired"),
          variant: "error"
        })
        return
      }
    }

    if (editingComponent.type !== 'metric' && isMetricCard) {
      if (categoryDimensions.length === 0) {
        toast({
          description: t("componentConfigDrawer.validation.categoryRequired"),
          variant: "error"
        })
        return
      } else if (categoryDimensions.some(dim => invalidFieldIds.has(dim.id))) {
        toast({
          description: t("componentConfigDrawer.validation.invalidCategoryFields"),
          variant: "error"
        })
        return
      }
    }

    if (valueDimensions.length === 0) {
      toast({
        description: t("componentConfigDrawer.validation.metricRequired"),
        variant: "error"
      })
      return
    } else if (valueDimensions.some(dim => invalidFieldIds.has(dim.id))) {
      toast({
        description: t("componentConfigDrawer.validation.invalidMetricFields"),
        variant: "error"
      })
      return
    }

    if (!editingComponent.dataset_code) {
      toast({
        description: t("componentConfigDrawer.validation.datasetRequired"),
        variant: "error"
      })
      return
    }

    if (currentChartHasStack && stackDimensions.length === 0) {
      toast({
        description: t("componentConfigDrawer.validation.stackRequired"),
        variant: "error"
      })
      return
    }
    const dataConfig = getDataConfig(limitType, limitValue, editingComponent.data_config?.timeFilter)

    updateEditingComponent({
      data_config: dataConfig,
      type: chartType,
      title: title,
      style_config: styleConfig,
      dataset_code: editingComponent.dataset_code
    })

    if (e.isTrusted) {
      refreshChart(editingComponent.id)

      toast({
        description: t("componentConfigDrawer.dialog.chartUpdated"),
        variant: "success"
      })
    }
  }, [
    editingComponent,
    chartType,
    title,
    styleConfig,
    limitType,
    limitValue,
    getDataConfig,
    updateEditingComponent,
    refreshChart,
    categoryDimensions,
    valueDimensions,
    stackDimensions,
    currentChartHasStack,
    invalidFieldIds,
    toast,
    t
  ])

  // 时间范围改变
  const handleTimeFilterChange = useCallback((val: any) => {
    console.log("Day Range Change:", val);

    if (editingComponent) {
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

  const PanelHeader = useCallback(({ title: panelTitle, onCollapse, icon }: any) => (
    <div className="px-4 py-3 border-b flex items-center justify-between bg-muted/20">
      <h3 className="text-base font-semibold">{panelTitle}</h3>
      <Button variant="ghost" size="icon" onClick={onCollapse} className="h-8 w-8">
        {icon}
      </Button>
    </div>
  ), [])

  const CollapseLabel = useCallback(({ label, onClick, icon, styleLabel }: any) => (
    <div className="h-full flex flex-col items-center cursor-pointer hover:bg-accent/50 transition-colors" onClick={onClick}>
      <div className="m-[18px]">{icon}</div>
      <div className="w-full h-[2px] bg-gray-100 mb-4"></div>
      <div className="writing-mode-vertical text-sm font-medium tracking-[6px]">{label}</div>
      <div className="writing-mode-vertical mt-4 text-sm font-medium tracking-[6px]">{styleLabel}</div>

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
          onSave={(chartLinkConfig) => {
            console.log('保存查询配置:', chartLinkConfig)

            // 构建 QueryConfig
            const queryConfig: QueryConfig = {
              linkedComponentIds: chartLinkConfig.chartIds || [],
              queryConditions: {
                id: editingComponent?.data_config?.queryConditions?.id || generateUUID(4),
                displayType: chartLinkConfig.displayType === "时间" ? "single" : "range",
                timeGranularity: chartLinkConfig.timeGranularity === "年月" ? "year_month" :
                  chartLinkConfig.timeGranularity === "年月日时" ? "year_month_day_hour" : "year_month_day",
                hasDefaultValue: chartLinkConfig.isDefault,
                defaultValue: chartLinkConfig.isDefault ? {
                  type: 'custom' as const,
                  startDate: new Date(chartLinkConfig.dateRange.start).getTime(),
                  endDate: new Date(chartLinkConfig.dateRange.end).getTime()
                } : {
                  type: 'all' as const
                }
              }
            }

            console.log('生成的 QueryConfig:', queryConfig)

            // 更新组件配置
            updateEditingComponent({
              // 保持其他字段不变，只更新 data_config
              data_config: queryConfig
            })

            // const dashboardStore = useEditorDashboardStore.getState();
            // dashboardStore.updateComponent(editingComponent.id, {
            //   data_config: queryConfig
            // })

            // 刷新查询组件
            refreshChart(editingComponent.id)
          }}
          onCancel={() => console.log('取消')}
        />
      ) : (
        <>
          <div className={`border-r flex flex-col h-full transition-all duration-300 ${configCollapsed.basic ? "w-12" : "w-[280px]"} shrink-0`}>
            {configCollapsed.basic ? (
              <CollapseLabel
                label={t("componentConfigDrawer.basicConfig")}
                styleLabel={t("componentConfigDrawer.styleConfigTab")}
                onClick={() => toggleCollapse('basic')}
                icon={<ListIndentDecrease className="w-4 h-4" />}
              />
            ) : (
              <div className="flex-1 flex flex-col overflow-hidden">
                <PanelHeader
                  title={t("componentConfigDrawer.basicConfig")}
                  onCollapse={() => toggleCollapse('basic')}
                  icon={<ListIndentIncrease className="w-4 h-4" />}
                />
                <div className="flex-1 overflow-y-auto pl-4 pr-4 pb-6 pt-4 space-y-6">
                  <div className="border-b -mx-4 px-4">
                    <div className="flex gap-6 text-sm">
                      <Tab active={configTab === "basic"} onClick={() => setConfigTab("basic")}>
                        {t("componentConfigDrawer.basicConfigTab")}
                      </Tab>
                      <Tab active={configTab === "style"} onClick={() => setConfigTab("style")}>
                        {t("componentConfigDrawer.styleConfigTab")}
                      </Tab>
                    </div>
                  </div>

                  {configTab === "basic" ? (
                    <>
                      {
                        editingComponent.type !== 'metric' && (
                          <>
                            {/* chart type */}
                            <FormBlock label={t("componentConfigDrawer.chartType")} required>
                              <ComponentPicker onSelect={(data) => {
                                // 更新图表类型
                                handleChartTypeChange(data.type);

                                // 自动将选中的图表名称设置为标题
                                const chartLabel = ChartGroupItems
                                  .flatMap(item => item.data)
                                  .find(item => item.type === data.type)?.label;
                                if (chartLabel) {
                                  setTitle(t(`chart.${chartLabel}`));
                                }
                              }} maxHeight={500}>
                                <div className="relative w-full group">
                                  <div className="flex h-[28px] w-full items-center justify-between rounded-md border border-gray-300 bg-white px-3 py-2 text-sm transition-colors hover:border-gray-400 cursor-pointer">
                                    {/* 文本区域 */}
                                    <div className="flex items-center gap-2 flex-1 min-w-0">
                                      <img
                                        src={`${__APP_ENV__.BASE_URL}/assets/dashboard/${chartType}.png`}
                                        className="w-4 h-4 shrink-0"
                                        alt={chartType}
                                      />
                                      <span className="truncate text-gray-700">
                                        {t(
                                          `chart.${ChartGroupItems
                                            .flatMap(item => item.data)
                                            .find(item => item.type === chartType)?.label}`
                                        ) || t("componentConfigDrawer.selectChartType")}
                                      </span>
                                    </div>

                                    {/* ChevronDown */}
                                    <ChevronDown className="h-4 w-4 text-gray-500 flex-shrink-0" />
                                  </div>
                                </div>
                              </ComponentPicker>
                            </FormBlock>
                            {/* 类别轴 / 维度 */}
                            {isMetricCard && (
                              <>
                                <CollapsibleBlock
                                  title={t("componentConfigDrawer.categoryAxis")}
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

                                {currentChartHasStack && (
                                  <CollapsibleBlock
                                    title={t("componentConfigDrawer.stackItem")}
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
                            )}

                          </>
                        )
                      }

                      {/* 值轴 / 指标 */}
                      <CollapsibleBlock
                        title={t("componentConfigDrawer.valueAxis")}
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
                          onFormatChange={handleMetricFormatChange}
                        />
                      </CollapsibleBlock>

                      {/* 排序优先级 */}
                      {(editingComponent.type !== 'metric' && isMetricCard) && <CollapsibleBlock title={t("componentConfigDrawer.sortPriority")}>
                        <div className="space-y-1 border rounded-md p-[2px]">
                          {sortPriorityFields.length === 0 ? (
                            <div className="text-xs text-muted-foreground text-center py-2">
                              {t("componentConfigDrawer.sortHint")}
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
                                onDragEnd={() => setDraggingId(null)}
                                onDragOver={(e) => e.preventDefault()}
                                onDrop={(e) => {
                                  e.preventDefault()
                                  const sourceId = e.dataTransfer.getData('text/plain')
                                  if (!sourceId) return
                                  chartState.handleDropSortPriority(field)
                                }}
                                className={`flex items-center gap-2 px-3 py-2 h-[28px] border rounded-md bg-muted/20 ${draggingId === field.id ? 'opacity-50' : ''}`}
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
                          <label className="text-sm font-medium">{t("componentConfigDrawer.filter")}</label>
                        </div>

                        {!filterGroup || filterGroup.conditions.length === 0 ? (
                          <div
                            className="text-sm text-muted-foreground text-center w-[244px] h-[36px] py-2 border rounded-md bg-muted/20 cursor-pointer hover:bg-muted/30 transition-colors"
                            onClick={handleEditFilter}
                          >
                            <div className="inline-flex items-center h-[20px] px-2 text-xs">
                              {t("componentConfigDrawer.addFilterCondition")}
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-2 bg-blue-100 rounded-md border-blue-300">
                            <div className="flex items-center justify-between p-2 border rounded-md bg-muted/20 hover:bg-muted/40">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-blue-700">
                                  {t("componentConfigDrawer.filterConditionsAdded", { count: filterGroup.conditions.length })}
                                  {filterGroup.conditions.length > 1 && t("componentConfigDrawer.filterLogicHint", {
                                    logic: (filterGroup.logic?.toUpperCase() || 'AND')
                                  })}
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

                      <FormBlock label={t("componentConfigDrawer.timeRange")}>
                        <AdvancedDatePicker
                          granularity={'day'}
                          mode={'range'}
                          value={filter}
                          onChange={(val) => {
                            handleTimeFilterChange(val);
                            setFilter(val);
                          }}
                          placeholder={t("componentConfigDrawer.selectTimeRange")}
                        />
                      </FormBlock>

                      {/* 结果显示 */}
                      {(editingComponent.type !== 'metric' && isMetricCard) && <FormBlock label={t("componentConfigDrawer.resultsDisplay")}>
                        <RadioGroup
                          value={limitType}
                          onValueChange={(value: "all" | "limit") => setLimitType(value)}
                          className="flex gap-6"
                        >
                          <div className="flex items-center space-x-2">
                            <RadioGroupItem value="all" id="limit-all" />
                            <Label htmlFor="limit-all" className="text-sm cursor-pointer">
                              {t("componentConfigDrawer.allResults")}
                            </Label>
                          </div>
                          <div className="flex items-center space-x-2">
                            <RadioGroupItem value="limit" id="limit-limit" />
                            <div className="flex items-center gap-2">
                              <Input
                                className="w-20 h-8"
                                value={limitValue}
                                disabled={limitType !== "limit"}
                                onChange={(e) => setLimitValue(e.target.value)}
                              />
                              <Label htmlFor="limit-limit" className="text-sm text-muted-foreground cursor-pointer">
                                {t("componentConfigDrawer.limitResults")}
                              </Label>
                            </div>
                          </div>
                        </RadioGroup>
                      </FormBlock>}

                      {/* <Button id="config_save" className="w-full h-10 mt-4" onClick={handleUpdateChart}>
                        {t("componentConfigDrawer.updateChartData")}
                      </Button> */}
                    </>
                  ) : (
                    <StyleConfigPanel
                      config={editingComponent?.style_config || styleConfig}
                      type={editingComponent.type}
                      onChange={(newConfig) => {
                        chartState.setStyleConfig(newConfig)
                        if (editingComponent) {
                          updateEditingComponent({
                            style_config: newConfig
                          })
                        }
                      }}
                      key={editingComponent.id}
                    />
                  )}
                </div>
                {/* 底部固定更新按钮（不随滚动） */}
                <div className="px-4 py-3 border-t bg-background">
                  <Button
                    id="config_save"
                    className="w-full h-10"
                    onClick={handleUpdateChart}
                  >
                    {t("componentConfigDrawer.updateChartData")}
                  </Button>
                </div>

              </div>
            )}
          </div>
          <div className={`flex flex-col h-full transition-all duration-300 ${configCollapsed.data ? "w-12 shrink-0" : "w-[160px]"}`}>
            {configCollapsed.data ? (
              <CollapseLabel
                label={t("componentConfigDrawer.dataSelection")}
                onClick={() => toggleCollapse('data')}
                icon={<ListIndentDecrease className="w-4 h-4" />}
              />
            ) : (
              <div className="flex-1 flex flex-col overflow-hidden">
                <PanelHeader
                  title={t("componentConfigDrawer.dataSelection")}
                  onCollapse={() => toggleCollapse('data')}
                  icon={<ListIndentIncrease className="w-4 h-4" />}
                />
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
          <DialogHeader>
            <DialogTitle>{t("componentConfigDrawer.dialog.editDisplayName")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <div className="text-sm text-muted-foreground mb-1">
                {t("componentConfigDrawer.dialog.originalName")}
              </div>
              <div className="text-sm font-medium px-2 py-1 bg-muted rounded">{editingDimension?.originalName}</div>
            </div>
            <div>
              <div className="text-sm font-medium mb-1">
                {t("componentConfigDrawer.dialog.displayNameRequired")}
              </div>
              <Input
                value={editingDimension?.displayName || ''}
                onChange={(e) => setEditingDimension(prev => prev ? { ...prev, displayName: e.target.value } : null)}
                placeholder={t("componentConfigDrawer.dialog.enterDisplayName")}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
              {t("componentConfigDrawer.dialog.cancel")}
            </Button>
            <Button onClick={saveDisplayName}>
              {t("componentConfigDrawer.dialog.confirm")}
            </Button>
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
        dataset_code={editingComponent?.dataset_code}
      />
    </div>
  )
}