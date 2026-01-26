// ComponentConfigDrawer.tsx
"use client"

import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { ChevronDown, GripVertical, ListIndentDecrease, ListIndentIncrease, PencilLine, X } from "lucide-react"

import { useCallback, useEffect, useMemo, useState } from "react"

import { Label } from "@/components/bs-ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { useTranslation } from "react-i18next"
import { ChartType, ComponentStyleConfig, QueryConfig, TimeRangeMode } from "../../types/dataConfig"
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
const FULL_DEFAULT_STYLE_CONFIG: ComponentStyleConfig = {
  themeColor: "professional-blue",
  bgColor: "",

  title: "",
  titleFontSize: 16,
  titleBold: true,
  titleItalic: false,
  titleUnderline: false,
  titleStrikethrough: false,
  titleAlign: "left",
  titleColor: "",

  xAxisTitle: "",
  xAxisFontSize: 14,
  xAxisBold: false,
  xAxisItalic: false,
  xAxisUnderline: false,
  xAxisStrikethrough: false,
  xAxisAlign: "center",
  xAxisColor: "#000000",

  yAxisTitle: "",
  yAxisFontSize: 14,
  yAxisBold: false,
  yAxisItalic: false,
  yAxisUnderline: false,
  yAxisStrikethrough: false,
  yAxisAlign: "center",
  yAxisColor: "#000000",

  legendPosition: "bottom",
  legendFontSize: 12,
  legendBold: false,
  legendItalic: false,
  legendUnderline: false,
  legendStrikethrough: false,
  legendAlign: "left",
  legendColor: "#999",

  showSubtitle: false,
  subtitle: "",
  subtitleFontSize: 14,
  subtitleStrikethrough: false,
  subtitleBold: false,
  subtitleItalic: false,
  subtitleUnderline: false,
  subtitleAlign: "center",
  subtitleColor: "",

  metricFontSize: 14,
  metricBold: false,
  metricItalic: false,
  metricUnderline: false,
  metricStrikethrough: false,
  metricAlign: "center",
  metricColor: "#000000",

  showLegend: true,
  showAxis: true,
  showDataLabel: false,
  showGrid: true,
}

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

  const [filter, setFilter] = useState();
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
  useEffect(() => {
    if (editingComponent) {
      // 从组件配置中获取时间范围
      const timeFilter = editingComponent.data_config?.timeFilter;
      if (timeFilter) {
        let shortcutKey;
        if (timeFilter.type === 'recent_days' && timeFilter.recentDays) {
          shortcutKey = `last_${timeFilter.recentDays}`;
        } else {
          shortcutKey = '';
        }

        setFilter({
          startTime: timeFilter.startDate,
          endTime: timeFilter.endDate,
          shortcutKey: shortcutKey,
          isDynamic: timeFilter.mode === "dynamic"

        });
      } else {
        setFilter(null);
      }

      // 从组件配置中获取限制选项
      const limitConfig = editingComponent.data_config?.resultLimit;
      if (limitConfig?.limit) {
        setLimitType("limit");
        setLimitValue(limitConfig.limit);

      } else {
        // 默认值
        setLimitType("all");
        setLimitValue("1000");
      }

      // 重置折叠状态
      setConfigCollapsed({
        basic: false,
        data: false,
        category: false,
        stack: false,
        value: false
      });

      // 重置配置标签页
      setConfigTab("basic");
    }
  }, [editingComponent?.id]);
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
    const isFieldInCategoryOrStack = (fieldId: string) => {
      return (
        categoryDimensions.some(dim => dim.fieldId === fieldId) ||
        stackDimensions.some(dim => dim.fieldId === fieldId)
      )
    }
    if (field.role === 'dimension') {
      if (isFieldInCategoryOrStack(safeFieldId)) {
        toast({
          description: t("useChartState.warn.fieldExists"),
          variant: "warning"
        })
        return
      }
      if (categoryDimensions.length < 2 && isMetricCard) {
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
      } else if (currentChartHasStack && stackDimensions.length === 0 && isMetricCard) {
        if (isFieldInCategoryOrStack(safeFieldId)) {
          toast({
            description: t("useChartState.warn.fieldExists"),
            variant: "warning"
          })
          return
        }
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
        if (!isMetricCard) {
          toast({
            description: t("componentConfigDrawer.toast.metricReached"),
            variant: "warning"
          })
        } else {
          toast({
            description: t("componentConfigDrawer.toast.dimensionLimitReached"),
            variant: "warning"
          })
        }

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
        // if (currentIsVirtual && !hasVirtualMetric) {
        //   toast({
        //     description: t("componentConfigDrawer.toast.virtualMetricConflict"),
        //     variant: "warning"
        //   })
        //   return
        // }

        // if (!currentIsVirtual && hasVirtualMetric) {
        //   toast({
        //     description: t("componentConfigDrawer.toast.virtualMetricConflict"),
        //     variant: "warning"
        //   })
        //   return
        // }

        // 多个虚拟指标
        // if (currentIsVirtual && hasVirtualMetric) {
        //   toast({
        //     description: t("componentConfigDrawer.toast.multipleVirtualMetric"),
        //     variant: "warning"
        //   })
        //   return
        // }
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
  editingComponent?.dataset_code
  // 数据集改变
  const handleDatasetChange = useCallback((datasetCode: string) => {
    if (editingComponent) {
      updateEditingComponent({ dataset_code: datasetCode })
      // 只有当数据集真正改变时才重置
      if (editingComponent.dataset_code !== datasetCode) {
        setFilterGroup({
          logic: "and",
          conditions: []
        })
      }
    }
  }, [editingComponent, updateEditingComponent, setFilterGroup])

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
      const trimmedName = editingDimension.displayName?.trim();
      if (!trimmedName) {
        toast({
          description: t("componentConfigDrawer.dialog.displayRequired"),
          variant: "error"
        });
        return;
      }
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
    if (editingComponent) {
      // 获取当前的数据配置
      const currentDataConfig = editingComponent.data_config || {}

      updateEditingComponent({
        data_config: {
          ...currentDataConfig,
          filters: newFilterGroup.conditions,
          filtersLogic: newFilterGroup.logic
        }
      })
    }
    setFilterGroup(newFilterGroup)
    setFilterDialogOpen(false)
  }, [])

  // 切换折叠
  const toggleCollapse = useCallback((section: keyof typeof configCollapsed) => {
    setConfigCollapsed(prev => ({ ...prev, [section]: !prev[section] }))
  }, [])

  const validateChartConfig = ({
    editingComponent,
    chartType,
    isMetricCard,
    categoryDimensions,
    valueDimensions,
    stackDimensions,
    currentChartHasStack,
    invalidFieldIds
  }) => {
    if (editingComponent.type !== 'query' && editingComponent.type !== 'metric') {
      if (!chartType) return { isValid: false, errorKey: 'chartTypeRequired' };
    }

    if (editingComponent.type !== 'metric' && isMetricCard) {
      if (categoryDimensions.length === 0) {
        return { isValid: false, errorKey: 'categoryRequired' };
      }
      if (categoryDimensions.some(dim => invalidFieldIds.has(dim.id))) {
        return { isValid: false, errorKey: 'invalidCategoryFields' };
      }
    }

    if (valueDimensions.length === 0) {
      return { isValid: false, errorKey: 'metricRequired' };
    }
    if (valueDimensions.some(dim => invalidFieldIds.has(dim.id))) {
      return { isValid: false, errorKey: 'invalidMetricFields' };
    }

    if (!editingComponent.dataset_code) {
      return { isValid: false, errorKey: 'datasetRequired' };
    }

    // if (currentChartHasStack && stackDimensions.length === 0) {
    //   return { isValid: false, errorKey: 'stackRequired' };
    // }

    return { isValid: true };
  };
  // 更新图表 - 添加校验
  const handleUpdateChart = useCallback((e) => {
    if (!editingComponent) return

    if (e.isTrusted) {
      const { isValid, errorKey } = validateChartConfig({
        editingComponent,
        chartType,
        isMetricCard,
        categoryDimensions,
        valueDimensions,
        stackDimensions,
        currentChartHasStack,
        invalidFieldIds
      });

      if (!isValid) {
        if (errorKey) {
          toast({
            description: t(`componentConfigDrawer.validation.${errorKey}`),
            variant: "error"
          });
        }
        return;
      }
    }

    const dataConfig = getDataConfig(limitType, limitValue, editingComponent.data_config?.timeFilter)
    // dataConfig.isConfigured = e.isTrusted

    const finalStyleConfig = styleConfig && Object.keys(styleConfig).length > 0
      ? { ...styleConfig }
      : { ...FULL_DEFAULT_STYLE_CONFIG }

    if (dataConfig?.metrics?.[0]?.fieldName && !isMetricCard) {
      finalStyleConfig.title = dataConfig.metrics[0].fieldName
    } else {
      finalStyleConfig.title = ''
    }
    updateEditingComponent({
      data_config: dataConfig,
      type: chartType,
      title: finalStyleConfig.title || dataConfig.metrics[0].fieldName,
      style_config: finalStyleConfig,
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
    sortPriorityFields,
    chartState.sortPriorityOrder,
    toast,
    t
  ])
  const isStackedChart = (type: ChartType) =>
    type.startsWith('grouped-');
  // 时间范围改变
  const handleTimeFilterChange = useCallback((val: any) => {
    if (editingComponent) {
      let recentDays;
      if (val?.shortcutKey) {
        if (val.shortcutKey.startsWith('last_')) {
          recentDays = val.shortcutKey.replace('last_', '');
        } else {
          recentDays = val.shortcutKey;
        }
      }
      updateEditingComponent({
        ...editingComponent,
        data_config: {
          ...editingComponent.data_config,
          timeFilter: val ? {
            recentDays: recentDays,
            type: val.shortcutKey ? "recent_days" : "custom",
            startDate: val.startTime,
            endDate: val.endTime,
            mode: val.isDynamic ? "dynamic" : "fixed"
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
      <div className="m-[20px]">{icon}</div>
      <div className="w-full h-[2px] bg-gray-100 mb-4"></div>
      <div className="writing-mode-vertical text-sm font-medium tracking-[6px]">{label}</div>
      <div className="writing-mode-vertical mt-4 text-sm font-medium tracking-[6px]">{styleLabel}</div>

    </div>
  ), [])
  const handleAggregationChange = useCallback((dimensionId: string, aggregation: string) => {
    chartState.setValueDimensions(prev =>
      prev.map(d =>
        d.id === dimensionId
          ? { ...d, aggregation }
          : d
      )
    );
  }, [chartState]);
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

            const { dateRange } = chartLinkConfig
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
                  shortcutKey: chartLinkConfig.dateRange.shortcutKey ? parseInt(chartLinkConfig.dateRange.shortcutKey.replace('last_', '')) : undefined,
                  // startDate: new Date(chartLinkConfig.dateRange.start).getTime(),
                  // endDate: new Date(chartLinkConfig.dateRange.end).getTime(),

                  type: chartLinkConfig.dateRange.shortcutKey ? "recent_days" : "custom",
                  mode: dateRange.isDynamic ? TimeRangeMode.Dynamic : TimeRangeMode.Fixed,
                  recentDays: dateRange.shortcutKey ? parseInt(dateRange.shortcutKey.replace('last_', '')) : undefined,
                  startDate: dateRange.start,
                  endDate: dateRange.end
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
          onCancel={() => {
            updateEditingComponent(null)
          }}
        />
      ) : (
        <>
          <div className={`border-r flex flex-col h-full transition-all duration-300 ${configCollapsed.basic ? "w-12" : "w-[260px]"} shrink-0`}>
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

                                // 判断是否是指标卡
                                const isMetricChart = data.type === 'metric';

                                const chartLabel = ChartGroupItems
                                  .flatMap(item => item.data)
                                  .find(item => item.type === data.type)?.label;

                                // 判断当前图表类型的名称
                                const currentChartLabel = ChartGroupItems
                                  .flatMap(item => item.data)
                                  .find(item => item.type === chartType)?.label;
                                const currentChartDisplayName = currentChartLabel ? t(`chart.${currentChartLabel}`) : '';

                                let newTitle = title;

                                if (isMetricChart) {
                                  if (valueDimensions.length > 0) {
                                    newTitle = valueDimensions[0].displayName;
                                  }
                                } else {
                                  const userCustomizedTitle = editingComponent.title !== currentChartDisplayName && editingComponent.title !== '';
                                  newTitle = userCustomizedTitle ? editingComponent.title : (chartLabel ? t(`chart.${chartLabel}`) : title);
                                }
                                if (!isMetricChart && chartLabel) {
                                  setTitle(newTitle);
                                }

                                // 立即触发图表更新
                                if (editingComponent) {
                                  // 使用当前实际的限制配置
                                  const currentLimitType = limitType;
                                  const currentLimitValue = limitValue;

                                  // 获取当前数据配置
                                  const dataConfig = getDataConfig(currentLimitType, currentLimitValue, editingComponent.data_config?.timeFilter);

                                  // 根据新图表类型调整配置
                                  const STACKED_CHART_TYPES = new Set<ChartType>([
                                    ChartType.StackedBar,
                                    ChartType.StackedHorizontalBar,
                                    ChartType.StackedLine
                                  ]);

                                  const isNewChartStacked = STACKED_CHART_TYPES.has(data.type);
                                  const isCurrentChartStacked = currentChartHasStack;

                                  let updatedDataConfig = { ...dataConfig };

                                  // 处理堆叠维度
                                  if (isCurrentChartStacked && !isNewChartStacked) {
                                    // 从堆叠图切换到非堆叠图：移除堆叠维度配置
                                    updatedDataConfig = {
                                      ...updatedDataConfig,
                                      stackDimension: undefined,
                                      dimensions: updatedDataConfig.dimensions || [],
                                      metrics: updatedDataConfig.metrics || []
                                    };
                                  } else if (!isCurrentChartStacked && isNewChartStacked) {
                                    // 从非堆叠图切换到堆叠图：清空堆叠维度
                                    updatedDataConfig = {
                                      ...updatedDataConfig,
                                      stackDimension: undefined, // 清空堆叠维度
                                      dimensions: updatedDataConfig.dimensions || [],
                                      metrics: updatedDataConfig.metrics || []
                                    };
                                  }
                                  if (data.type === 'metric') {
                                    updateEditingComponent({
                                      type: data.type,
                                      data_config: updatedDataConfig,
                                      title: newTitle,
                                      style_config: {
                                        ...styleConfig
                                      },
                                      dataset_code: editingComponent.dataset_code
                                    });
                                  } else {
                                    updateEditingComponent({
                                      type: data.type,
                                      data_config: updatedDataConfig,
                                      title: newTitle,
                                      style_config: {
                                        ...styleConfig,
                                        title: newTitle
                                      },
                                      dataset_code: editingComponent.dataset_code
                                    });
                                  }

                                  // 刷新图表
                                  refreshChart(editingComponent.id);
                                }
                              }} maxHeight={400}>
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
                                    onDrop={(e) => handleDrop(e, 'category', isMetricCard)}
                                    onDelete={(dimensionId) => handleDeleteDimension('category', dimensionId)}
                                    onSortChange={(dimensionId, sortValue) => handleSortChange('category', dimensionId, sortValue)}
                                    onEditDisplayName={(dimensionId, originalName, displayName) =>
                                      openEditDialog('category', dimensionId, originalName, displayName)
                                    }
                                  />
                                </CollapsibleBlock>

                                {currentChartHasStack && (
                                  <CollapsibleBlock
                                    title={isStackedChart(chartType) ? t("componentConfigDrawer.subCategory") : t("componentConfigDrawer.stackItem")}
                                    collapsed={configCollapsed.stack}
                                    onCollapse={() => toggleCollapse('stack')}
                                  >
                                    <DimensionBlock
                                      invalidIds={invalidFieldIds}
                                      isDimension={true}
                                      isStack={'stack'}
                                      dimensions={stackDimensions}
                                      isDragOver={dragOverSection === 'stack'}
                                      onDragOver={(e) => handleDragOver(e, 'stack')}
                                      onDragLeave={handleDragLeave}
                                      onDrop={(e) => handleDrop(e, 'stack', isMetricCard)}
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
                          onAggregationChange={handleAggregationChange}
                          isMetricCard={isMetricCard}
                          invalidIds={invalidFieldIds}
                          isDimension={false}
                          dimensions={valueDimensions}
                          isDragOver={dragOverSection === 'value'}
                          onDragOver={(e) => handleDragOver(e, 'value')}
                          onDragLeave={handleDragLeave}
                          onDrop={(e) => handleDrop(e, 'value', isMetricCard)}
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
                          {sortPriorityFields?.length === 0 ? (
                            <div className="text-xs text-muted-foreground text-center py-2">
                              {t("componentConfigDrawer.sortHint")}
                            </div>
                          ) : (
                            sortPriorityFields.map((field) => (
                              <div
                                key={field.id}
                                draggable
                                onMouseDown={() => { }}
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
                                  handleDropSortPriority(field)
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
                            className="text-sm text-muted-foreground text-center w-[216px] h-[36px] py-2 border rounded-md bg-muted/20 cursor-pointer hover:bg-muted/30 transition-colors"
                            onClick={handleEditFilter}
                          >
                            <div className="inline-flex items-center h-[20px] px-2 text-xs">
                              {t("componentConfigDrawer.addFilterCondition")}
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-2 bg-blue-100 rounded-md border-blue-300 group">
                            <div className="flex items-center justify-between p-2 border rounded-md bg-muted/20 hover:bg-muted/40">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-blue-700">
                                  {t("componentConfigDrawer.filterConditionsAdded", { count: filterGroup.conditions.length })}
                                </span>
                              </div>
                              <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center gap-1">
                                <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleEditFilter}>
                                  <PencilLine className="h-3 w-3" />
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
                        <div className="space-y-1 flex flex-1 w-full">
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
                        </div>
                      </FormBlock>




                      {/* <Button id="config_save" className="w-full h-10 mt-4" onClick={handleUpdateChart}>
                        {t("componentConfigDrawer.updateChartData")}
                      </Button> */}
                    </>
                  ) : (
                    <StyleConfigPanel
                      config={editingComponent?.style_config || styleConfig}
                      type={editingComponent.type}
                      FULL_DEFAULT_STYLE_CONFIG={FULL_DEFAULT_STYLE_CONFIG}
                      onChange={(newConfig) => {
                        chartState.setStyleConfig(newConfig)
                        if (editingComponent) {
                          updateEditingComponent({
                            title: newConfig.title,
                            style_config: newConfig
                          })
                        }
                      }}
                      key={editingComponent.id}
                    />
                  )}
                </div>
                {/* 底部固定更新按钮（不随滚动） */}
                {configTab !== "style" && <div className="px-4 py-3 border-t bg-background">
                  {/* 结果显示 */}
                  {(editingComponent.type !== 'metric' && isMetricCard) &&
                    <div>
                      <RadioGroup
                        value={limitType}
                        onValueChange={(value: "all" | "limit") => setLimitType(value)}
                        className="flex justify-between gap-4"
                      >
                        <div className=" text-sm font-medium mt-1">
                          {t("componentConfigDrawer.resultsDisplay")}
                        </div>
                        <div className="flex">
                          <div className="flex items-center space-x-2 mr-1">
                            <RadioGroupItem value="all" id="limit-all" />
                            <Label htmlFor="limit-all" className="text-sm cursor-pointer whitespace-nowrap">
                              {t("componentConfigDrawer.allResults")}
                            </Label>
                          </div>
                          <div className="flex items-center space-x-2">
                            <RadioGroupItem value="limit" id="limit-limit" />
                            <div className="flex items-center gap-2">
                              <Input
                                className="w-16 h-7 text-sm appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                                type="number"
                                value={limitValue}
                                disabled={limitType !== "limit"}
                                onChange={(e) => {
                                  const value = e.target.value;
                                  if (value === '' || /^\d+$/.test(value)) {
                                    const num = parseInt(value);
                                    if (value === '' || (num >= 1 && num <= 1000)) {
                                      setLimitValue(value);
                                    }
                                  }
                                }}
                                onBlur={(e) => {
                                  const value = e.target.value;
                                  const num = parseInt(value);
                                  if (value === '' || isNaN(num)) {
                                    setLimitValue('1');
                                  } else if (num < 1) {
                                    setLimitValue('1');
                                  } else if (num > 1000) {
                                    setLimitValue('1000');
                                  } else {
                                    setLimitValue(num.toString());
                                  }
                                }}
                                min={1}
                                max={1000}
                                placeholder="1000"
                              />
                            </div>
                          </div>
                        </div>

                      </RadioGroup>
                    </div>
                  }
                  <Button
                    id="config_save"
                    className="w-full h-10 mt-[12px]"
                    onClick={handleUpdateChart}
                  >
                    {t("componentConfigDrawer.updateChartData")}
                  </Button>
                </div>}

              </div>
            )}
          </div>
          <div className={`flex flex-col h-full transition-all duration-300 ${configCollapsed.data ? "w-12 shrink-0" : "w-[180px]"}`}>
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
                    isMetricCard={editingComponent?.type === 'metric'}
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
                maxLength={15}
                className={(editingDimension?.displayName?.length || 0) >= 15 ? 'border-red-500 focus-visible:ring-red-500' : ''}
              />
              {(editingDimension?.displayName?.length || 0) >= 15 && (
                <div className="text-xs text-red-500 mt-1">
                  {t("componentConfigDrawer.dialog.displayMaxLength", { max: 15 })}
                </div>
              )}
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
        filtersLogic={editingComponent?.data_config.filtersLogic}
        dimensions={[...categoryDimensions, ...stackDimensions, ...valueDimensions]}
      />
    </div>
  )
}