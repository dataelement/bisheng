// useChartState.tsx
"use client"

import { useState, useMemo, useEffect, useCallback, useRef } from "react"
import { ChartType, ComponentStyleConfig, DataConfig } from "../../types/dataConfig"
import { generateUUID } from "@/components/bs-ui/utils"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { useTranslation } from "react-i18next"


export function useChartState(initialComponent: any) {
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

  const isStackedChart = (type: ChartType) => type.startsWith('stacked-')
  // 初始化逻辑
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

      const dc = initialComponent.data_config
      const newChartType = initialComponent.type || 'bar'

      setChartType(newChartType)
      setTitle(initialComponent.title || '')

      setStyleConfigState(initialComponent.style_config || {})

      // 初始化维度数据
      if (dc) {
        console.log('数据配置:', dc)

        // 1. 初始化普通维度（类别轴）
        if (dc.dimensions && dc.dimensions.length > 0) {
          const formattedCategoryDims = dc.dimensions.map((dim, index) => ({
            id: `category_${index}_${Date.now()}`,
            fieldId: dim.fieldId,
            name: dim.fieldCode,
            displayName: dim.displayName || dim.fieldName,
            originalName: dim.fieldName,
            sort: dim.sort || null,
            timeGranularity: dim.timeGranularity || null,
            sortPriority: 0,
            fieldType: 'dimension'
          }))
          setCategoryDimensions(formattedCategoryDims)
          console.log('设置类别维度:', formattedCategoryDims)
        }

        // 2. 初始化堆叠维度
        if (dc.stackDimension) {
          const formattedStackDim = {
            id: `stack_0_${Date.now()}`,
            fieldId: dc.stackDimension.fieldId,
            name: dc.stackDimension.fieldCode,
            displayName: dc.stackDimension.displayName || dc.stackDimension.fieldName,
            originalName: dc.stackDimension.fieldName,
            sort: dc.stackDimension.sort || null,
            timeGranularity: dc.timeGranularity || null,
            sortPriority: 0,
            fieldType: 'dimension'
          }
          setStackDimensions([formattedStackDim])
          console.log('设置堆叠维度:', formattedStackDim)
        }

        // 3. 初始化指标（value）
        if (dc.metrics && dc.metrics.length > 0) {
          const valueDims = dc.metrics.map((metric, index) => ({
            id: `value_${index}_${Date.now()}`,
            fieldId: metric.fieldId,
            name: metric.fieldCode,
            displayName: metric.displayName || metric.fieldName,
            originalName: metric.fieldName,
            sort: metric.sort || null,
            sortPriority: 0,
            fieldType: 'metric',
            aggregation: metric.aggregation || 'sum',
            numberFormat: metric.numberFormat || {
              type: 'number',
              decimalPlaces: 2,
              thousandSeparator: true
            }
          }))
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
              fieldType: filter.fieldType || 'string',
              filterType: filter.filterType || 'conditional',
              operator: filter.operator || 'eq',
              value: filter.value
            }))
          })
        }
      }
    }

    if (!initialComponent) {
      editingComponentIdRef.current = null
    }
  }, [initialComponent?.id])

  // 计算属性
  const sortPriorityFields = useMemo(() => {
    const allFields = [
      ...categoryDimensions.map(d => ({ ...d, section: 'category' as const })),
      ...stackDimensions.map(d => ({ ...d, section: 'stack' as const })),
      ...valueDimensions.map(d => ({ ...d, section: 'value' as const }))
    ]

    const uniqueFields = new Map()
    allFields.forEach(field => {
      if (!uniqueFields.has(field.fieldId)) {
        uniqueFields.set(field.fieldId, field)
      }
    })

    const uniqueFieldsArray = Array.from(uniqueFields.values())

    return uniqueFieldsArray.sort((a, b) => {
      const indexA = sortPriorityOrder.indexOf(a.id)
      const indexB = sortPriorityOrder.indexOf(b.id)
      if (indexA === -1 && indexB === -1) return 0
      if (indexA === -1) return 1
      if (indexB === -1) return -1
      return indexA - indexB
    })
  }, [categoryDimensions, stackDimensions, valueDimensions, sortPriorityOrder])

  // 更新 sortPriorityOrder
  useEffect(() => {
    const allFields = [
      ...categoryDimensions.map(d => ({ ...d, section: 'category' })),
      ...stackDimensions.map(d => ({ ...d, section: 'stack' })),
      ...valueDimensions.map(d => ({ ...d, section: 'value' }))
    ]

    const timeField = allFields.find(
      f => f.name === 'timestamp' || f.fieldId === 'timestamp'
    )

    const otherFields = allFields.filter(
      f => f !== timeField
    )

    const orderedFields = timeField
      ? [timeField, ...otherFields]
      : otherFields

    setSortPriorityOrder(orderedFields.map(f => f.id))
  }, [
    categoryDimensions.length,
    stackDimensions.length,
    valueDimensions.length
  ])


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

  const handleDrop = useCallback((e: React.DragEvent, section: 'category' | 'stack' | 'value') => {
    e.preventDefault()
    e.stopPropagation()

    const dataStr = e.dataTransfer.getData('application/json')
    if (!dataStr) return

    try {
      const data = JSON.parse(dataStr)
      const fieldType = data.fieldType || 'dimension'

      // 转换section和fieldType为国际化文本
      const sectionText = t(`useChartState.sections.${section}`)
      const fieldTypeText = t(`useChartState.fieldTypes.${fieldType}`)

      if (
        (fieldType === 'metric' && (section === 'category' || section === 'stack')) ||
        (fieldType === 'dimension' && section === 'value')
      ) {
        console.warn(`字段类型 ${fieldTypeText} 不能拖拽到 ${sectionText} 区域`)
        toast({
          description: t('useChartState.warn.invalidFieldType', { fieldType: fieldTypeText, section: sectionText }),
          variant: "warning",
        })
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
      //指标维度只能有一个
      if (section === 'value' && valueDimensions.length >= 1) {
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
      if (alreadyExists) return

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
        fieldType
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
  }, [categoryDimensions, stackDimensions, valueDimensions, toast, t])

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
    setFilterGroup(null)
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

    const metrics = valueDimensions.map(metric => ({
      fieldId: metric.fieldId,
      fieldName: metric.originalName,
      fieldCode: metric.name,
      displayName: metric.displayName,
      sort: metric.sort,
      isVirtual: false,
      aggregation: metric.aggregation || 'sum',
      numberFormat: metric.numberFormat || {
        type: 'number' as const,
        decimalPlaces: 2,
        unit: undefined,
        suffix: undefined,
        thousandSeparator: true
      }
    }))

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
      fieldType: field.type
    }))

    // 5. 构建筛选条件
    const filters = filterGroup ? filterGroup.conditions.map((condition, index) => {
      return {
        id: condition.id || `filter_${Date.now()}_${index}`, // 确保有 fieldId
        fieldId: condition.fieldCode || '',
        fieldName: condition.fieldName || '',
        fieldType: condition.fieldType || 'string',
        operator: condition.operator || 'eq',
        value: condition.value || '',
        filterType: condition.filterType || 'conditional'
      }
    }) : []

    console.log('生成数据配置:', {
      dimensions,
      stackDimension,
      metrics,
      fieldOrder,
      filters,
      hasStack: stackDimensions.length > 0
    })

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
      isConfigured: true,
    }
  }, [categoryDimensions, stackDimensions, valueDimensions, filterGroup])

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