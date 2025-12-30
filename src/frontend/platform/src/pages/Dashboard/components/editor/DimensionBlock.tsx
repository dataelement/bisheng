"use client"

import { useState } from "react"
import { Button } from "@/components/bs-ui/button"
import { Settings, X, ChevronRight, Check } from "lucide-react"

interface DimensionItem {
  id: string
  name: string
  displayName: string
  sort: 'none' | 'asc' | 'desc'
  fieldType: 'dimension' | 'metric'
  originalName: string
  aggregation?: string
  format?: string
  sortPriority?: number
}

interface DimensionBlockProps {
  isDimension: boolean
  dimensions: DimensionItem[]
  maxDimensions?: number
  isDragOver?: boolean
  onDragOver?: (e: React.DragEvent) => void
  onDragLeave?: () => void
  onDrop?: (e: React.DragEvent) => void
  onDelete: (dimensionId: string) => void
  onSortChange?: (dimensionId: string, sortValue: 'none' | 'asc' | 'desc') => void
  onEditDisplayName: (dimensionId: string, originalName: string, displayName: string) => void
  onAggregationChange?: (dimensionId: string, aggregation: string) => void
  onFormatChange?: (dimensionId: string, format: string) => void
}

export function DimensionBlock({ 
  isDimension,
  dimensions = [],
  maxDimensions,
  isDragOver = false,
  onDragOver,
  onDragLeave,
  onDrop,
  onDelete,
  onSortChange,
  onEditDisplayName,
  onAggregationChange,
  onFormatChange
}: DimensionBlockProps) {
  const [hoveredDimension, setHoveredDimension] = useState<string | null>(null)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [hoveredMenuItem, setHoveredMenuItem] = useState<{
    dimensionId: string
    menuType: 'sort' | 'aggregation' | 'format'
  } | null>(null)

  // 获取字段样式
  const getFieldTypeStyle = (fieldType: 'dimension' | 'metric') => {
    if (fieldType === 'dimension') {
      return 'bg-blue-100 text-blue-800 border-blue-200'
    } else {
      return 'bg-orange-100 text-orange-800 border-orange-200'
    }
  }

  // 选项配置
  const aggregationOptions = [
    { label: '求和', value: 'sum' },
    { label: '平均', value: 'avg' },
    { label: '计数', value: 'count' },
    { label: '最大值', value: 'max' },
    { label: '最小值', value: 'min' }
  ]

  const sortOptions = [
    { label: '无', value: 'none' },
    { label: '升序', value: 'asc' },
    { label: '降序', value: 'desc' }
  ]

  const formatOptions = [
    { label: '默认格式', value: 'default' },
    { label: '数字格式', value: 'number' },
    { label: '百分比', value: 'percent' },
    { label: '货币格式', value: 'currency' }
  ]

  // 设置按钮点击
  const handleSettingsClick = (dimensionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setOpenMenuId(openMenuId === dimensionId ? null : dimensionId)
    setHoveredMenuItem(null)
  }

  // 菜单项悬停
  const handleMenuItemHover = (dimensionId: string, menuType: 'sort' | 'aggregation' | 'format') => {
    if (openMenuId === dimensionId) {
      setHoveredMenuItem({ dimensionId, menuType })
    }
  }

  return (
    <div className="space-y-3"
      onDragOver={(e) => {
        e.preventDefault()
        e.stopPropagation()
        if (onDragOver) onDragOver(e)
      }}
      onDragLeave={(e) => {
        e.preventDefault()
        e.stopPropagation()
        if (onDragLeave) onDragLeave()
      }}
      onDrop={(e) => {
        e.preventDefault()
        e.stopPropagation()
        if (onDrop) onDrop(e)
      }}
    >
      {/* 维度/指标列表 */}
      {dimensions.length > 0 ? (
        <div className="space-y-2">
          {dimensions.map((dimension) => (
            <div
              key={dimension.id}
              className="relative group"
              onMouseEnter={() => setHoveredDimension(dimension.id)}
              onMouseLeave={() => setHoveredDimension(null)}
            >
              <div 
                className={`flex items-center justify-between gap-2 p-1 rounded-md border ${getFieldTypeStyle(dimension.fieldType || 'dimension')} hover:bg-opacity-80 transition-colors`}
              >
                {/* 字段名称 */}
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-medium truncate">{dimension.displayName}</span>
                </div>

                {/* 操作按钮 */}
                <div className={`flex items-center gap-1 ${hoveredDimension === dimension.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 transition-opacity'}`}>
                  {/* 设置按钮 */}
                  <div className="relative">
                    <Button 
                      variant="ghost" 
                      size="icon" 
                      className="h-6 w-6 p-0"
                      onClick={(e) => handleSettingsClick(dimension.id, e)}
                    >
                      <Settings className="h-3 w-3" />
                    </Button>
                    
                    {/* 菜单 */}
                    {openMenuId === dimension.id && (
                      <div 
                        className="absolute right-full top-0 mr-1 bg-white border rounded-md shadow-lg z-20 p-2 min-w-[120px]"
                        onClick={(e) => e.stopPropagation()}
                        onMouseLeave={() => setHoveredMenuItem(null)}
                      >
                        {/* 维度菜单 */}
                        {dimension.fieldType === 'dimension' ? (
                          <>
                            {/* 排序 */}
                            <div className="relative">
                              <div 
                                className={`flex items-center justify-between px-2 py-1 text-xs rounded cursor-pointer ${hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'sort' ? 'bg-gray-100' : 'hover:bg-gray-100'}`}
                                onMouseEnter={() => handleMenuItemHover(dimension.id, 'sort')}
                              >
                                <span>排序</span>
                                <ChevronRight className="h-3 w-3" />
                              </div>
                              
                              {/* 排序子菜单 */}
                              {hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'sort' && (
                                <div 
                                  className="absolute left-full top-0 ml-1 bg-white border rounded-md shadow-lg z-30 p-2 min-w-[90px]"
                                  onMouseEnter={() => handleMenuItemHover(dimension.id, 'sort')}
                                  onMouseLeave={() => setHoveredMenuItem(null)}
                                >
                                  {sortOptions.map((option) => (
                                    <button
                                      key={option.value}
                                      className={`flex items-center justify-between w-full px-2 py-1 text-xs rounded ${dimension.sort === option.value ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100'}`}
                                      onClick={() => {
                                        onSortChange?.(dimension.id, option.value as 'none' | 'asc' | 'desc')
                                        setOpenMenuId(null)
                                        setHoveredMenuItem(null)
                                      }}
                                    >
                                      <span>{option.label}</span>
                                      {dimension.sort === option.value && <Check className="h-3 w-3" />}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                            
                            <div className="h-px bg-gray-200 my-1"></div>
                            
                            {/* 编辑显示名称 */}
                            <button
                              className="block w-full text-left px-2 py-1 text-xs hover:bg-gray-100 rounded"
                              onClick={() => {
                                onEditDisplayName(dimension.id, dimension.originalName, dimension.displayName)
                                setOpenMenuId(null)
                              }}
                            >
                              编辑显示名称
                            </button>
                          </>
                        ) : (
                          <>
                            {/* 指标菜单 */}
                            {/* 汇总方式 */}
                            <div className="relative">
                              <div 
                                className={`flex items-center justify-between px-2 py-1 text-xs rounded cursor-pointer ${hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'aggregation' ? 'bg-gray-100' : 'hover:bg-gray-100'}`}
                                onMouseEnter={() => handleMenuItemHover(dimension.id, 'aggregation')}
                              >
                                <span>汇总方式</span>
                                <ChevronRight className="h-3 w-3" />
                              </div>
                              
                              {/* 汇总方式子菜单 */}
                              {hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'aggregation' && (
                                <div 
                                  className="absolute left-full top-0 ml-1 bg-white border rounded-md shadow-lg z-30 p-2 min-w-[80px]"
                                  onMouseEnter={() => handleMenuItemHover(dimension.id, 'aggregation')}
                                  onMouseLeave={() => setHoveredMenuItem(null)}
                                >
                                  {aggregationOptions.map((option) => (
                                    <button
                                      key={option.value}
                                      className={`flex items-center justify-between w-full px-2 py-1 text-xs rounded ${dimension.aggregation === option.value ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100'}`}
                                      onClick={() => {
                                        onAggregationChange?.(dimension.id, option.value)
                                        setOpenMenuId(null)
                                        setHoveredMenuItem(null)
                                      }}
                                    >
                                      <span>{option.label}</span>
                                      {dimension.aggregation === option.value && <Check className="h-3 w-3" />}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                            
                            {/* 排序 */}
                            <div className="relative mt-1">
                              <div 
                                className={`flex items-center justify-between px-2 py-1 text-xs rounded cursor-pointer ${hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'sort' ? 'bg-gray-100' : 'hover:bg-gray-100'}`}
                                onMouseEnter={() => handleMenuItemHover(dimension.id, 'sort')}
                              >
                                <span>排序</span>
                                <ChevronRight className="h-3 w-3" />
                              </div>
                              
                              {/* 排序子菜单 */}
                              {hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'sort' && (
                                <div 
                                  className="absolute left-full top-0 ml-1 bg-white border rounded-md shadow-lg z-30 p-2 min-w-[90px]"
                                  onMouseEnter={() => handleMenuItemHover(dimension.id, 'sort')}
                                  onMouseLeave={() => setHoveredMenuItem(null)}
                                >
                                  {sortOptions.map((option) => (
                                    <button
                                      key={option.value}
                                      className={`flex items-center justify-between w-full px-2 py-1 text-xs rounded ${dimension.sort === option.value ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100'}`}
                                      onClick={() => {
                                        onSortChange?.(dimension.id, option.value as 'none' | 'asc' | 'desc')
                                        setOpenMenuId(null)
                                        setHoveredMenuItem(null)
                                      }}
                                    >
                                      <span>{option.label}</span>
                                      {dimension.sort === option.value && <Check className="h-3 w-3" />}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                            
                            {/* 数值格式 */}
                            <div className="relative mt-1">
                              <div 
                                className={`flex items-center justify-between px-2 py-1 text-xs rounded cursor-pointer ${hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'format' ? 'bg-gray-100' : 'hover:bg-gray-100'}`}
                                onMouseEnter={() => handleMenuItemHover(dimension.id, 'format')}
                              >
                                <span>数值格式</span>
                                <ChevronRight className="h-3 w-3" />
                              </div>
                              
                              {/* 数值格式子菜单 */}
                              {hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'format' && (
                                <div 
                                  className="absolute left-full top-0 ml-1 bg-white border rounded-md shadow-lg z-30 p-2 min-w-[90px]"
                                  onMouseEnter={() => handleMenuItemHover(dimension.id, 'format')}
                                  onMouseLeave={() => setHoveredMenuItem(null)}
                                >
                                  {formatOptions.map((option) => (
                                    <button
                                      key={option.value}
                                      className={`flex items-center justify-between w-full px-2 py-1 text-xs rounded ${dimension.format === option.value ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100'}`}
                                      onClick={() => {
                                        onFormatChange?.(dimension.id, option.value)
                                        setOpenMenuId(null)
                                        setHoveredMenuItem(null)
                                      }}
                                    >
                                      <span>{option.label}</span>
                                      {dimension.format === option.value && <Check className="h-3 w-3" />}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                            
                            <div className="h-px bg-gray-200 my-1"></div>
                            
                            {/* 编辑显示名称 */}
                            <button
                              className="block w-full text-left px-2 py-1 text-xs hover:bg-gray-100 rounded"
                              onClick={() => {
                                onEditDisplayName(dimension.id, dimension.originalName, dimension.displayName)
                                setOpenMenuId(null)
                              }}
                            >
                              编辑显示名称
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>

                  {/* 删除按钮 */}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 p-0 hover:bg-red-200"
                    onClick={() => onDelete(dimension.id)}
                    title="删除字段"
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              </div>
              
              {/* 点击外部关闭菜单 */}
              {openMenuId === dimension.id && (
                <div 
                  className="fixed inset-0 z-10" 
                  onClick={() => {
                    setOpenMenuId(null)
                    setHoveredMenuItem(null)
                  }}
                />
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className={`
          border border-dashed rounded-md px-3 py-2
          ${isDragOver 
            ? 'border-primary bg-blue-50' 
            : 'border-gray-300 bg-gray-50'
          }
        `}>
          <div className="text-sm text-gray-400">
            {isDimension ? '拖拽维度字段至此' : '拖拽指标字段至此'}
          </div>
        </div>
      )}

      {/* 达到最大维度数提示 */}
      {maxDimensions && dimensions.length >= maxDimensions && (
        <div className="text-xs text-red-500 text-center mt-1">
          最多允许添加{maxDimensions}个字段
        </div>
      )}
    </div>
  )
}