// useChartState.tsx
"use client"

import { useState, useMemo, useEffect, useCallback, useRef } from "react"
import { ChartType, ComponentStyleConfig, DataConfig } from "../../types/dataConfig"
import { CHART_TYPES } from "./ComponentConfigDrawer"
import { generateUUID } from "@/components/bs-ui/utils"
import { useToast } from "@/components/bs-ui/toast/use-toast"

// 默认样式配置常量
const DEFAULT_STYLE_CONFIG: ComponentStyleConfig = {
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
}

export function useChartState(initialComponent: any) {
  const editingComponentIdRef = useRef<string | null>(null)
  
  const [chartType, setChartType] = useState<ChartType>('bar')
  const [title, setTitle] = useState('')
  const [styleConfig, setStyleConfig] = useState<ComponentStyleConfig>(DEFAULT_STYLE_CONFIG)
  const [categoryDimensions, setCategoryDimensions] = useState<any[]>([])
  const [stackDimensions, setStackDimensions] = useState<any[]>([])
  const [valueDimensions, setValueDimensions] = useState<any[]>([])
  const [dragOverSection, setDragOverSection] = useState<string | null>(null)
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [sortPriorityOrder, setSortPriorityOrder] = useState<string[]>([])
  const [filterGroup, setFilterGroup] = useState<any>(null)
  const { toast } = useToast()

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
      
      // 合并样式配置
      const newStyleConfig = initialComponent.style_config 
        ? { ...DEFAULT_STYLE_CONFIG, ...initialComponent.style_config }
        : DEFAULT_STYLE_CONFIG
      setStyleConfig(newStyleConfig)

      // 初始化维度数据
      if (dc) {
        console.log('数据配置:', dc)
        
        // 判断是否为堆叠图表
        const isStackChart = CHART_TYPES.find(item => item.value === newChartType)?.hasStack || false
        console.log('是否为堆叠图表:', isStackChart)
        
        // 1. 初始化普通维度（类别轴）
        if (dc.dimensions && dc.dimensions.length > 0) {
          const formattedCategoryDims = dc.dimensions.map((dim, index) => ({
            id: `category_${index}_${Date.now()}`,
            fieldId: dim.fieldId,
            name: dim.fieldCode,
            displayName: dim.displayName || dim.fieldName,
            originalName: dim.fieldName,
            sort: dim.sort || 'none',
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
            sort: dc.stackDimension.sort || 'none',
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
            sort: metric.sort || 'none',
            sortPriority: 0,
            fieldType: 'metric',
            aggregation: metric.aggregation || 'sum'
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
  }, [initialComponent?.id]) // 只依赖组件ID

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
      ...categoryDimensions.map(d => ({ ...d, section: 'category' as const })),
      ...stackDimensions.map(d => ({ ...d, section: 'stack' as const })),
      ...valueDimensions.map(d => ({ ...d, section: 'value' as const }))
    ]

    const newOrder = allFields.map(field => field.id)
    setSortPriorityOrder(newOrder)
  }, [categoryDimensions.length, stackDimensions.length, valueDimensions.length])

  const currentChartHasStack = useMemo(() => {
    const chart = CHART_TYPES.find(item => item.value === chartType)
    return chart?.hasStack || false
  }, [chartType])

  // 图表类型切换
  const handleChartTypeChange = useCallback((value: ChartType) => {
    const selectedChart = CHART_TYPES.find(item => item.value === value)
    const isNewStackChart = selectedChart?.hasStack || false
    const isCurrentStackChart = currentChartHasStack
    
    setChartType(value)
    setTitle(selectedChart?.label || '')

    // 如果从堆叠切换到非堆叠，需要处理堆叠维度
    if (isCurrentStackChart && !isNewStackChart && stackDimensions.length > 0) {
      // 如果有堆叠维度，可以将其移动到类别维度（如果类别维度有空位）
      const stackDim = stackDimensions[0]
      if (categoryDimensions.length < 2) {
        // 将堆叠维度移动到类别维度
        setCategoryDimensions(prev => [...prev, {
          ...stackDim,
          id: `category_${Date.now()}`,
          section: 'category'
        }])
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

      if (
        (fieldType === 'metric' && (section === 'category' || section === 'stack')) ||
        (fieldType === 'dimension' && section === 'value')
      ) {
        console.warn(`字段类型 ${fieldType} 不能拖拽到 ${section} 区域`)
              toast({
          description: `字段类型 ${fieldType} 不能拖拽到 ${section} 区域`,
          variant: "warning",
        })
        setDragOverSection(null)
        return
      }
      
      // 堆叠维度只能有一个
      if (section === 'stack' && stackDimensions.length >= 1) {
        console.warn('堆叠维度只能有一个，请先删除现有的堆叠维度')
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
        sort: 'none' as const,
        sortPriority: 0,
        fieldType
      }

      if (section === 'category') {
        if (categoryDimensions.length >= 2) {
        console.warn('类别维度最多只能有 2 个')
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
  }, [categoryDimensions, stackDimensions, valueDimensions])

  const handleDeleteDimension = useCallback((section: 'category' | 'stack' | 'value', dimensionId: string) => {
    if (section === 'category') {
      setCategoryDimensions(prev => prev.filter(d => d.id !== dimensionId))
    } else if (section === 'stack') {
      setStackDimensions(prev => prev.filter(d => d.id !== dimensionId))
    } else if (section === 'value') {
      setValueDimensions(prev => prev.filter(d => d.id !== dimensionId))
    }
  }, [])

  const handleSortChange = useCallback((section: 'category' | 'stack' | 'value', dimensionId: string, sortValue: 'none' | 'asc' | 'desc') => {
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
      conditions: [{ id: generateUUID(6) }]
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
    sort: dim.sort === 'none' ? null : dim.sort,
    timeGranularity: ''
  }))

  const stackDimension = stackDimensions.length > 0 ? {
    fieldId: stackDimensions[0].fieldId,
    fieldName: stackDimensions[0].originalName,
    fieldCode: stackDimensions[0].name,
    displayName: stackDimensions[0].displayName,
    sort: stackDimensions[0].sort === 'none' ? null : stackDimensions[0].sort,
    timeGranularity: ''
  } : undefined

  const metrics = valueDimensions.map(metric => ({
    fieldId: metric.fieldId,
    fieldName: metric.originalName,
    fieldCode: metric.name,
    displayName: metric.displayName,
    sort: metric.sort === 'none' ? null : metric.sort,
    isVirtual: false,
    aggregation: metric.aggregation || 'sum',
    numberFormat: { type: 'number' as const, decimalPlaces: 2, unit: undefined, suffix: undefined, thousandSeparator: true }
  }))
    // 4. 构建字段顺序 - 注意字段类型
  const fieldOrder = [
    ...categoryDimensions.slice(0, 2).map(d => ({ fieldId: d.fieldId, fieldType: 'dimension' })),
    ...stackDimensions.slice(0, 1).map(d => ({ fieldId: d.fieldId, fieldType: 'stack_dimension' })),
    ...valueDimensions.map(m => ({ fieldId: m.fieldId, fieldType: 'metric' })),
  ]
    // 5. 构建筛选条件
    const filters = filterGroup ? filterGroup.conditions.map((condition, index) => ({
      id: condition.id || `filter_${Date.now()}_${index}`,
      fieldCode: condition.fieldCode || '',
      fieldType: condition.fieldType || 'string',
      operator: condition.operator || 'eq',
      value: condition.value || '',
      filterType: condition.filterType || 'conditional'
    })) : []

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
      }
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