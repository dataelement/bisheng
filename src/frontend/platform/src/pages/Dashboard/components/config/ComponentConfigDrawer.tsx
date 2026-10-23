// @ts-strict-ignore
import { Button, notification } from '@bisheng/ui';


import { useComponentEditorStore,useEditorDashboardStore } from "@/store/dashboardStore";
import { useCallback,useEffect,useMemo,useState } from "react";
import { useTranslation } from "react-i18next";
import { ChartType } from "../../types/dataConfig";
import { ComponentConfigView } from "./ComponentConfigView";
import { FULL_DEFAULT_STYLE_CONFIG } from "./dashboardStyleDefaults";
import { DatasetField } from "./DatasetSelector";
import { useChartState } from "./useChartState";
// ComponentConfigDrawer.tsx

export function useComponentConfigController() {
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
  const [filter, setFilter] = useState<import("../AdvancedDatePicker").DatePickerValue | undefined>();
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
        notification.open({ type: "warning", description: String(t("useChartState.warn.fieldExists") ?? '') })
        return
      }
      if (categoryDimensions.length < 2 && isMetricCard) {
        if (isFieldAlreadyAdded(safeFieldId, 'category')) {
          notification.open({ type: "warning", description: String(t("componentConfigDrawer.toast.fieldAlreadyExists", {
              section: t("componentConfigDrawer.sections.category")
            }) ?? '') })
          return
        }
        const newDimension = {
          id: `${safeFieldId}-${Date.now()}`,
          fieldId: safeFieldId,
          displayName: field.displayName || field.fieldName,
          originalName: field.displayName || field.fieldName,
          fieldType: field.role,
          timeGranularity: field.timeGranularity,
          isDivide: field.isDivide,
          sort: null
        }
        chartState.setCategoryDimensions(prev => [...prev, newDimension])
      } else if (currentChartHasStack && stackDimensions.length === 0 && isMetricCard) {
        if (isFieldInCategoryOrStack(safeFieldId)) {
          notification.open({ type: "warning", description: String(t("useChartState.warn.fieldExists") ?? '') })
          return
        }
        if (isFieldAlreadyAdded(safeFieldId, 'stack')) {
          notification.open({ type: "warning", description: String(t("componentConfigDrawer.toast.fieldAlreadyExists", {
              section: t("componentConfigDrawer.sections.stack")
            }) ?? '') })
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
          notification.open({ type: "warning", description: String(t("componentConfigDrawer.toast.metricReached") ?? '') })
        } else {
          notification.open({ type: "warning", description: String(t("componentConfigDrawer.toast.dimensionLimitReached") ?? '') })
        }
      }
    } else if (field.role === 'metric') {
      const maxMetricCount = getMaxMetricCount(chartType)
      const hasVirtualMetric = valueDimensions.some(d => d.isVirtual)
      const currentIsVirtual = isVirtualMetric(field)
      if (valueDimensions.length >= maxMetricCount) {
        notification.open({ type: "warning", description: String(t("componentConfigDrawer.toast.metricLimitReached", {
            count: maxMetricCount
          }) ?? '') })
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
        notification.open({ type: "warning", description: String(t("componentConfigDrawer.toast.fieldAlreadyExists", {
            section: t("componentConfigDrawer.sections.value")
          }) ?? '') })
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
        isVirtual: currentIsVirtual,
        isDivide: field.isDivide,
      }
      chartState.setValueDimensions(prev => [...prev, newMetric])
    }
  }, [editingComponent, categoryDimensions, stackDimensions, valueDimensions, currentChartHasStack, chartState, t])
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
      if (!trimmedName || editingDimension.displayName.length > 15) {
        notification.open({ type: "error", description: String(t("componentConfigDrawer.dialog.displayRequired") ?? '') });
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
          notification.open({ type: "error", description: String(t(`componentConfigDrawer.validation.${errorKey}`) ?? '') });
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
    } else if (chartType !== ChartType.Metric) {
      finalStyleConfig.title = editingComponent.title
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
      notification.open({ type: "success", description: String(t("componentConfigDrawer.dialog.chartUpdated") ?? '') })
    }
  }, [editingComponent, chartType, title, styleConfig, limitType, limitValue, getDataConfig, updateEditingComponent, refreshChart, categoryDimensions, valueDimensions, stackDimensions, currentChartHasStack, invalidFieldIds, sortPriorityFields, chartState.sortPriorityOrder, t])
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
      <Button variant="text" size="medium" onClick={onCollapse} className="h-8 w-8" color="default" iconOnly>
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
        <label className="text-sm font-medium flex items-center gap-1 text-foreground">
          {required && <span className="text-red-500">*</span>}
          {blockTitle}
        </label>
      </div>
      {!collapsed && children}
    </div>
  ), [])
  const handleCloseQuery = () => updateEditingComponent(null);
  return {
  handleCloseQuery, editingComponent, configCollapsed, toggleCollapse, updateEditingComponent, refreshChart,
  CollapseLabel, t, PanelHeader, Tab, configTab, setConfigTab,
  FormBlock, handleChartTypeChange, chartType, title, valueDimensions, setTitle,
  limitType, limitValue, getDataConfig, currentChartHasStack, chartState, styleConfig,
  isMetricCard, CollapsibleBlock, invalidFieldIds, categoryDimensions, dragOverSection, handleDragOver,
  handleDragLeave, handleDrop, handleDeleteDimension, handleSortChange, openEditDialog, isStackedChart,
  stackDimensions, handleAggregationChange, handleMetricFormatChange, sortPriorityFields, setDraggingId, handleDropSortPriority,
  draggingId, filterGroup, handleEditFilter, handleDeleteFilter, filter, handleTimeFilterChange,
  setFilter, setLimitType, setLimitValue, handleUpdateChart, handleDatasetChange, handleDragStart,
  setDatasetFields, handleFieldClick, editDialogOpen, setEditDialogOpen, editingDimension, setEditingDimension,
  saveDisplayName, filterDialogOpen, setFilterDialogOpen, handleSaveFilter, datasetFields };
}
export function ComponentConfigDrawer() { return <ComponentConfigView controller={useComponentConfigController()} /> }
