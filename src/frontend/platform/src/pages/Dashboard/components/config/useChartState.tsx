// useChartState.tsx
"use client"

import { useState, useMemo, useEffect, useCallback, useRef } from "react"
import { ChartType, ComponentStyleConfig, DashboardComponent, DataConfig } from "../../types/dataConfig"
import { generateUUID } from "@/components/bs-ui/utils"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { useTranslation } from "react-i18next"


export function useChartState(initialComponent: DashboardComponent) {
  const { t } = useTranslation("dashboard")
  const editingComponentIdRef = useRef<string | null>(null)

  const [chartType, setChartType] = useState<ChartType>('bar')
  const [title, setTitle] = useState('')
  const [styleConfig, setStyleConfigState] = useState<ComponentStyleConfig>(() => {
    return initialComponent?.style_config || {}
  });

  const [categoryDimensions, setCategoryDimensions] = useState<any[]>([])
  const [stackDimensions, setStackDimensions] = useState<any[]>([])
  const [valueDimensions, setValueDimensions] = useState<any[]>([])
  const [dragOverSection, setDragOverSection] = useState<string | null>(null)
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [sortPriorityOrder, setSortPriorityOrder] = useState<string[]>([])
  const [filterGroup, setFilterGroup] = useState<any>(null)
  const { toast } = useToast()
  const { updateEditingComponent } = useComponentEditorStore();
  const { refreshChart } = useEditorDashboardStore();
  const setStyleConfig = useCallback((newConfig: ComponentStyleConfig) => {
    // 更新本地状态
    setStyleConfigState(newConfig);

  }, [initialComponent, updateEditingComponent, refreshChart]);

  const isStackedChart = (type: ChartType) =>
    type.startsWith('stacked-') || type.startsWith('grouped-');
  // 初始化逻辑
  // 在 useEffect 初始化中添加 sortPriorityOrder 的初始化
  useEffect(() => {
    const componentId = initialComponent?.id
    const currentId = editingComponentIdRef.current

    if (componentId && currentId !== componentId) {
      console.log('重新初始化组件配置，因为组件ID变化:', componentId)
      console.log('原始组件数据:', initialComponent)

      editingComponentIdRef.current = componentId

      // 清空之前的维度数据
      setCategoryDimensions([])
      setStackDimensions([])
      setValueDimensions([])
      setFilterGroup(null)
      // 清空排序顺序
      setSortPriorityOrder([])

      const dc = initialComponent.data_config
      const newChartType = initialComponent.type || 'bar'

      setChartType(newChartType)
      setTitle(initialComponent.title || '')
      setStyleConfigState(initialComponent.style_config || {})

      // 初始化维度数据
      if (dc) {
        // console.log('数据配置:', dc)

        const newCategoryDimensions: any[] = []
        const newStackDimensions: any[] = []
        const newValueDimensions: any[] = []
        const fieldIdToComponentId = new Map<string, string>()

        // 1. 初始化普通维度（类别轴）
        if (dc.dimensions && dc.dimensions.length > 0) {
          const formattedCategoryDims = dc.dimensions.map((dim, index) => {
            const componentId = `category_${index}_${Date.now()}`
            fieldIdToComponentId.set(dim.fieldId, componentId)
            return {
              id: componentId,
              fieldId: dim.fieldId,
              name: dim.fieldCode,
              displayName: dim.displayName || dim.fieldName,
              originalName: dim.fieldName,
              sort: dim.sort || null,
              timeGranularity: dim.timeGranularity || null,
              sortPriority: 0,
              fieldType: 'dimension'
            }
          })
          newCategoryDimensions.push(...formattedCategoryDims)
          setCategoryDimensions(formattedCategoryDims)
          console.log('设置类别维度:', formattedCategoryDims)
        }

        // 2. 初始化堆叠维度
        if (dc.stackDimension) {
          const componentId = `stack_0_${Date.now()}`
          fieldIdToComponentId.set(dc.stackDimension.fieldId, componentId)
          const formattedStackDim = {
            id: componentId,
            fieldId: dc.stackDimension.fieldId,
            name: dc.stackDimension.fieldCode,
            displayName: dc.stackDimension.displayName || dc.stackDimension.fieldName,
            originalName: dc.stackDimension.fieldName,
            sort: dc.stackDimension.sort || null,
            timeGranularity: dc.timeGranularity || null,
            sortPriority: 0,
            fieldType: 'dimension'
          }
          newStackDimensions.push(formattedStackDim)
          setStackDimensions([formattedStackDim])
          console.log('设置堆叠维度:', formattedStackDim)
        }

        // 3. 初始化指标（value）
        if (dc.metrics && dc.metrics.length > 0) {
          const valueDims = dc.metrics.map((metric, index) => {
            const componentId = `value_${index}_${Date.now()}`
            fieldIdToComponentId.set(metric.fieldId, componentId)
            return {
              id: componentId,
              fieldId: metric.fieldId,
              name: metric.fieldCode,
              displayName: metric.displayName || metric.fieldName,
              originalName: metric.fieldName,
              sort: metric.sort || null,
              sortPriority: 0,
              fieldType: 'metric',
              isVirtual: metric.isVirtual || false,
              aggregation: metric.aggregation || 'sum',
              isDivide: metric.formula,
              numberFormat: metric.numberFormat || {
                type: 'number',
                decimalPlaces: 2,
                thousandSeparator: true
              }
            }
          })
          newValueDimensions.push(...valueDims)
          setValueDimensions(valueDims)
          console.log('设置指标维度:', valueDims)
        }

        // 4. 初始化筛选条件
        if (dc.filters) {
          setFilterGroup({
            logic: 'and',
            conditions: dc.filters.map(filter => ({
              id: filter.id || generateUUID(6),
              fieldId: filter.fieldId,
              fieldName: filter.fieldName,
              fieldType: filter.fieldType || 'string',
              filterType: filter.filterType || 'conditional',
              operator: filter.operator || 'eq',
              value: filter.value
            }))
          })
        }

        // 5. 初始化字段顺序
        let fieldOrderIds: string[] = []

        if (dc.fieldOrder && dc.fieldOrder.length > 0) {
          // 如果 data_config 中有 fieldOrder，使用其中的 fieldId 映射到 componentId
          fieldOrderIds = dc.fieldOrder
            .map(item => fieldIdToComponentId.get(item.fieldId))
            .filter(Boolean) as string[]
          // console.log('使用 data_config.fieldOrder 映射后的 componentIds:', fieldOrderIds)
        }

        // 如果没有 fieldOrder 或映射失败，使用默认顺序
        if (fieldOrderIds.length === 0) {
          const allComponentIds = [
            ...newCategoryDimensions.map(d => d.id),
            ...newStackDimensions.map(d => d.id),
            ...newValueDimensions.map(d => d.id)
          ]
          fieldOrderIds = allComponentIds
          // console.log('使用默认字段顺序:', fieldOrderIds)
        }

        setSortPriorityOrder(fieldOrderIds)
        // console.log('设置 sortPriorityOrder:', fieldOrderIds)
      }
    }

    if (!initialComponent) {
      editingComponentIdRef.current = null
    }
  }, [initialComponent?.id, initialComponent?.type])

  // 计算属性
  const sortPriorityFields = useMemo(() => {
    const allFields = [
      ...categoryDimensions,
      // ...stackDimensions,
      ...valueDimensions
    ]

    // 用 Map 保证 fieldId 唯一
    const uniqueFields = new Map<string, any>()
    allFields.forEach(f => {
      if (!uniqueFields.has(f.id)) uniqueFields.set(f.id, f)
    })

    return sortPriorityOrder
      .map(id => uniqueFields.get(id))
      .filter(Boolean) as typeof allFields
  }, [categoryDimensions, stackDimensions, valueDimensions, sortPriorityOrder])


  // 更新 sortPriorityOrder
  useEffect(() => {
    const allFields = [
      ...categoryDimensions,
      ...stackDimensions,
      ...valueDimensions
    ]

    if (sortPriorityOrder.length === 0) {
      const timeField = allFields.find(
        f => f.name === 'timestamp' || f.fieldId === 'timestamp'
      )

      const otherFields = allFields.filter(f => f !== timeField)

      const orderedFields = timeField ? [timeField, ...otherFields] : otherFields

      setSortPriorityOrder(orderedFields.map(f => f.id))
      return
    }

    const existingFieldIds = new Set(sortPriorityOrder)
    const newFields = allFields.filter(f => !existingFieldIds.has(f.id))

    if (newFields.length > 0) {
      const newTimeField = newFields.find(
        f => f.name === 'timestamp' || f.fieldId === 'timestamp'
      )

      const otherNewFields = newFields.filter(f => f !== newTimeField)

      if (newTimeField) {
        setSortPriorityOrder(prev => [newTimeField.id, ...prev])
      }

      if (otherNewFields.length > 0) {
        setSortPriorityOrder(prev => [...prev, ...otherNewFields.map(f => f.id)])
      }
    }
  }, [categoryDimensions, stackDimensions, valueDimensions])



  const currentChartHasStack = useMemo(() => {
    return isStackedChart(chartType)
  }, [chartType])


  // 图表类型切换
  const handleChartTypeChange = useCallback((value: ChartType) => {
    const isNewStackChart = isStackedChart(value)
    const isCurrentStackChart = currentChartHasStack

    setChartType(value)

    // 从堆叠 → 非堆叠：清理 stack 维度
    if (isCurrentStackChart && !isNewStackChart && stackDimensions.length > 0) {
      const stackDim = stackDimensions[0]

      if (categoryDimensions.length < 2) {
        setCategoryDimensions(prev => [
          ...prev,
          {
            ...stackDim,
            id: `category_${Date.now()}`,
          }
        ])
      }

      setStackDimensions([])
    }
  }, [stackDimensions, categoryDimensions, currentChartHasStack])


  // 拖拽相关方法
  const handleDragOver = useCallback((e: React.DragEvent, section: 'category' | 'stack' | 'value') => {
    e.preventDefault()
    setDragOverSection(section)
  }, [])

  const handleDragLeave = useCallback(() => {
    setDragOverSection(null)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent, section: 'category' | 'stack' | 'value', isMetricCard) => {
    e.preventDefault()
    e.stopPropagation()

    const dataStr = e.dataTransfer.getData('application/json')
    if (!dataStr) return

    try {
      const data = JSON.parse(dataStr)

      // 检查是否是已存在的维度移动（从其他区域拖过来的）
      if (data.isExistingDimension && data.sourceSection) {
        const sourceSection = data.sourceSection;
        const fieldId = data.fieldId;

        // 不允许同区域内移动
        if (sourceSection === section) {
          setDragOverSection(null);
          return;
        }

        // 特殊处理：从类别维度拖到堆叠维度
        if (sourceSection === 'category' && section === 'stack') {
          // 检查堆叠维度是否已满
          if (stackDimensions.length >= 1) {
            toast({
              description: t('useChartState.warn.maxStackDimension'),
              variant: "warning",
            });
            setDragOverSection(null);
            return;
          }

          // 从类别维度中查找要移动的维度
          const dimensionToMoveIndex = categoryDimensions.findIndex(dim => dim.id === data.id || dim.fieldId === fieldId);
          if (dimensionToMoveIndex === -1) {
            setDragOverSection(null);
            return;
          }

          const dimensionToMove = categoryDimensions[dimensionToMoveIndex];

          // 从类别维度中移除
          const updatedCategoryDimensions = categoryDimensions.filter((_, index) => index !== dimensionToMoveIndex);

          // 添加到堆叠维度
          const movedDimension = {
            ...dimensionToMove,
            id: `stack_${Date.now()}_${fieldId}`, // 生成新的ID
          };

          setCategoryDimensions(updatedCategoryDimensions);
          setStackDimensions([movedDimension]);

          setDragOverSection(null);
          return;
        }

        // 特殊处理：从堆叠维度拖到类别维度
        if (sourceSection === 'stack' && section === 'category') {
          // 检查类别维度是否已满
          if (categoryDimensions.length >= 2) {
            toast({
              description: t('useChartState.warn.maxCategoryDimensions'),
              variant: "warning",
            });
            setDragOverSection(null);
            return;
          }

          // 从堆叠维度中查找要移动的维度
          const dimensionToMove = stackDimensions.find(dim => dim.id === data.id || dim.fieldId === fieldId);
          if (!dimensionToMove) {
            setDragOverSection(null);
            return;
          }

          // 添加到类别维度
          const movedDimension = {
            ...dimensionToMove,
            id: `category_${Date.now()}_${fieldId}`, // 生成新的ID
          };

          // 清空堆叠维度
          setStackDimensions([]);
          setCategoryDimensions(prev => [...prev, movedDimension]);

          setDragOverSection(null);
          return;
        }
      }

      // 原有的新字段拖拽逻辑保持不变
      const fieldType = data.fieldType || 'dimension'

      // 转换section和fieldType为国际化文本
      const sectionText = t(`useChartState.sections.${section}`)
      const fieldTypeText = t(`useChartState.fieldTypes.${fieldType}`)

      if (
        (fieldType === 'metric' && (section === 'category' || section === 'stack')) ||
        (fieldType === 'dimension' && section === 'value')
      ) {
        console.warn(`字段类型 ${fieldTypeText} 不能拖拽到 ${sectionText} 区域`)
        if (!isMetricCard) {
          toast({
            description: t("componentConfigDrawer.toast.metricReached"),
            variant: "warning"
          })
        } else {
          toast({
            description: t('useChartState.warn.invalidFieldType', { fieldType: fieldTypeText, section: sectionText }),
            variant: "warning",
          })
        }
        setDragOverSection(null)
        return
      }

      // 堆叠维度只能有一个
      if (section === 'stack' && stackDimensions.length >= 1) {
        console.warn('堆叠维度只能有一个，请先删除现有的堆叠维度')
        toast({
          description: t('useChartState.warn.maxStackDimension'),
          variant: "warning",
        })
        setDragOverSection(null)
        return
      }

      const STACKED_CHART_TYPES = new Set(['stacked-bar', 'stacked-horizontal-bar', 'stacked-line']);
      const maxMetricCount = STACKED_CHART_TYPES.has(chartType) ? 3 : 1;

      //指标维度只能有一个
      if (section === 'value' && valueDimensions.length >= maxMetricCount) {
        console.warn('指标维度只能有一个，请先删除现有的指标维度')
        toast({
          description: t('useChartState.warn.metricLimitReached'),
          variant: "warning",
        })
        setDragOverSection(null)
        return
      }

      const fieldId = data.id || data.name || `field_${Date.now()}`
      const name = data.name || data.displayName || fieldId

      let currentDimensions: any[] = []
      if (section === 'category') currentDimensions = categoryDimensions
      if (section === 'stack') currentDimensions = stackDimensions
      if (section === 'value') currentDimensions = valueDimensions

      const alreadyExists = currentDimensions.some(dim => dim.fieldId === fieldId)
      if (alreadyExists) {
        console.warn('该字段已存在')
        toast({
          description: t('useChartState.warn.fieldExists'),
          variant: "warning",
        })
        setDragOverSection(null)
        return
      }

      if (section === 'category' || section === 'stack') {
        // 如果拖拽到分类维度，检查是否已在堆叠维度中存在
        if (section === 'category') {
          const existsInStack = stackDimensions.some(dim => dim.fieldId === fieldId)
          if (existsInStack) {
            console.warn('该字段已在堆叠维度中添加')
            toast({
              description: t("useChartState.warn.fieldExists"),
              variant: "warning"
            })
            setDragOverSection(null)
            return
          }
        }

        const otherCategories = categoryDimensions.filter(dim =>
          section === 'stack' || dim.fieldId !== fieldId
        )
        if (otherCategories.some(dim => dim.fieldId === fieldId)) {
          console.warn('该字段已在其他分类维度中添加')
          toast({
            description: t("useChartState.warn.fieldExists"),
            variant: "warning",
          })
          setDragOverSection(null)
          return
        }
      }

      const displayName = data.displayName || name
      const originalName = data.name || name

      const newDimension = {
        id: `${section}_${Date.now()}`,
        fieldId,
        name,
        displayName,
        originalName,
        sort: null,
        sortPriority: 0,
        timeGranularity: data.timeGranularity,
        fieldType,
        isDivide: data.isDivide,
      }

      if (section === 'category') {
        if (categoryDimensions.length >= 2) {
          console.warn('类别维度最多只能有 2 个')
          toast({
            description: t('useChartState.warn.maxCategoryDimensions'),
            variant: "warning",
          })
          setDragOverSection(null)
          return
        }
        setCategoryDimensions(prev => [...prev, newDimension])
      } else if (section === 'stack') {
        // 堆叠维度 - 特殊处理
        setStackDimensions([newDimension])
      } else if (section === 'value') {
        setValueDimensions(prev => [...prev, newDimension])
      }

      setDragOverSection(null)
    } catch (error) {
      console.error('拖拽数据解析失败:', error)
    }
  }, [categoryDimensions, stackDimensions, valueDimensions, toast, t, chartType])

  const handleDeleteDimension = useCallback((section: 'category' | 'stack' | 'value', dimensionId: string) => {
    if (section === 'category') {
      setCategoryDimensions(prev => prev.filter(d => d.id !== dimensionId))
    } else if (section === 'stack') {
      setStackDimensions(prev => prev.filter(d => d.id !== dimensionId))
    } else if (section === 'value') {
      setValueDimensions(prev => prev.filter(d => d.id !== dimensionId))
    }
  }, [])

  const handleSortChange = useCallback((section: 'category' | 'stack' | 'value', dimensionId: string, sortValue: null | 'asc' | 'desc') => {
    const updateDimensions = (prev: any[]) =>
      prev.map(d => d.id === dimensionId ? { ...d, sort: sortValue } : d)

    if (section === 'category') setCategoryDimensions(updateDimensions)
    if (section === 'stack') setStackDimensions(updateDimensions)
    if (section === 'value') setValueDimensions(updateDimensions)
  }, [])

  const handleDropSortPriority = useCallback((targetField: any) => {
    if (!draggingId || draggingId === targetField.id) return

    const sourceIndex = sortPriorityOrder.indexOf(draggingId)
    const targetIndex = sortPriorityOrder.indexOf(targetField.id)

    if (sourceIndex === -1 || targetIndex === -1) return

    const newOrder = [...sortPriorityOrder]
    const [moved] = newOrder.splice(sourceIndex, 1)
    newOrder.splice(targetIndex, 0, moved)

    setSortPriorityOrder(newOrder)
    setDraggingId(null)
  }, [draggingId, sortPriorityOrder])

  const handleAddFilter = useCallback(() => {
    setFilterGroup({
      logic: 'and',
      conditions: [{
        id: generateUUID(6),
        fieldId: '',
        fieldCode: '',
        fieldName: '',
        fieldType: 'string',
        operator: 'eq',
        value: '',
        filterType: 'conditional'
      }]
    })
  }, [])

  const handleDeleteFilter = useCallback(() => {
    setFilterGroup({ logic: "and", conditions: [] });
  }, [])

  // 获取数据配置
  const getDataConfig = useCallback((limitType: "all" | "limit", limitValue: string, timeFilter?: any): DataConfig => {
    const dimensions = categoryDimensions.slice(0, 2).map(dim => ({
      fieldId: dim.fieldId,
      fieldName: dim.originalName,
      fieldCode: dim.name,
      displayName: dim.displayName,
      sort: dim.sort,
      timeGranularity: dim.timeGranularity || null
    }))

    const stackDimension = stackDimensions.length > 0 ? {
      fieldId: stackDimensions[0].fieldId,
      fieldName: stackDimensions[0].originalName,
      fieldCode: stackDimensions[0].name,
      displayName: stackDimensions[0].displayName,
      sort: stackDimensions[0].sort,
      timeGranularity: stackDimensions[0].timeGranularity || null
    } : undefined

    const metrics = valueDimensions.map(metric => {
      let numberFormat;
      if (metric.isDivide === "divide") {
        console.log('检测到除法指标:', metric.displayName);
        if (metric.numberFormat) {
          if (metric.numberFormat.type === 'percent') {
            numberFormat = metric.numberFormat;
            console.log('已使用百分比格式:', numberFormat);
          } else {
            numberFormat = {
              type: 'percent' as const,
              decimalPlaces: metric.numberFormat.decimalPlaces || 2,
              unit: undefined,
              suffix: metric.numberFormat.suffix || '',
              thousandSeparator: false
            };
          }
        } else {
          numberFormat = {
            type: 'percent' as const,
            decimalPlaces: 2,
            unit: undefined,
            suffix: '',
            thousandSeparator: false
          };
        }
      } else {
        numberFormat = metric.numberFormat || {
          type: 'number' as const,
          decimalPlaces: 0,
          unit: undefined,
          suffix: undefined,
          thousandSeparator: true
        };
      }

      // console.log('最终 numberFormat:', numberFormat);

      return {
        fieldId: metric.fieldId,
        fieldName: metric.originalName,
        fieldCode: metric.name,
        displayName: metric.displayName,
        sort: metric.sort,
        isVirtual: metric.isVirtual,
        aggregation: metric.aggregation || 'sum',
        isDivide: metric.isDivide,
        formula: metric.isDivide === "divide" ? "divide" : undefined,
        numberFormat: numberFormat
      }
    })
    // 4. 构建字段顺序 - 按照 sortPriorityOrder 排序
    const allFields = [
      ...categoryDimensions.map(d => ({
        ...d,
        type: 'dimension' as const
      })),
      ...stackDimensions.map(d => ({
        ...d,
        type: 'stack_dimension' as const
      })),
      ...valueDimensions.map(m => ({
        ...m,
        type: 'metric' as const
      }))
    ]

    // 按照 sortPriorityOrder 排序
    const sortedFields = [...allFields].sort((a, b) => {
      const indexA = sortPriorityOrder.indexOf(a.id)
      const indexB = sortPriorityOrder.indexOf(b.id)

      // 如果都在排序列表中，按照列表顺序排序
      if (indexA !== -1 && indexB !== -1) {
        return indexA - indexB
      }

      // 如果有一个不在列表中，不在列表的排在后面
      if (indexA === -1 && indexB !== -1) return 1
      if (indexA !== -1 && indexB === -1) return -1

      // 都不在列表中，保持原有顺序
      return 0
    })

    // 构建 fieldOrder
    const fieldOrder = sortedFields.map(field => ({
      fieldId: field.fieldId,
      fieldType: field.type,
      displayName: field.displayName,
    }))

    // 5. 构建筛选条件
    const filters = filterGroup ? filterGroup.conditions.map((condition, index) => {
      return {
        id: condition.id || `filter_${Date.now()}_${index}`, // 确保有 fieldId
        fieldId: condition.fieldId || '',
        fieldName: condition.fieldName || '',
        fieldType: condition.fieldType || 'string',
        operator: condition.operator || 'eq',
        value: condition.value || '',
        filterType: condition.filterType || 'conditional'
      }
    }) : []

    // console.log('生成数据配置:', {
    //   dimensions,
    //   stackDimension,
    //   metrics,
    //   fieldOrder,
    //   filters,
    //   hasStack: stackDimensions.length > 0
    // })

    return {
      dimensions,
      stackDimension,
      metrics,
      fieldOrder,
      filters,
      timeFilter,
      resultLimit: {
        limitType: limitType === "limit" ? "limited" as const : "all" as const,
        ...(limitType === "limit" && { limit: Number(limitValue) })
      },
      filtersLogic: filterGroup?.logic || 'and',
      isConfigured: true,
    }
  }, [categoryDimensions, stackDimensions, valueDimensions, filterGroup, sortPriorityOrder])

  // 返回对象
  return {
    // 状态
    chartType,
    title,
    styleConfig,
    categoryDimensions,
    stackDimensions,
    valueDimensions,
    dragOverSection,
    filterGroup,
    draggingId,
    sortPriorityOrder,
    sortPriorityFields,
    currentChartHasStack,

    // 设置器
    setChartType,
    setTitle,
    setStyleConfig,
    setCategoryDimensions,
    setStackDimensions,
    setValueDimensions,
    setDragOverSection,
    setFilterGroup,
    setDraggingId,
    setSortPriorityOrder,

    // 方法
    handleChartTypeChange,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleDeleteDimension,
    handleSortChange,
    handleDropSortPriority,
    handleAddFilter,
    handleDeleteFilter,
    getDataConfig
  }
}