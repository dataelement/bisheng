"use client"

import { useState } from "react"
import { Button } from "@/components/bs-ui/button"
import { Settings, X, ChevronRight, Check } from "lucide-react"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio"
import { Label } from "@/components/bs-ui/label"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { useTranslation } from "react-i18next"

interface DimensionItem {
  id: string
  name: string
  displayName: string
  sort: null | 'asc' | 'desc'
  fieldType: 'dimension' | 'metric'
  originalName: string
  aggregation?: string
  format?: string
  numberFormat?: MetricFormat
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
  onSortChange?: (dimensionId: string, sortValue: null | 'asc' | 'desc') => void
  onEditDisplayName: (dimensionId: string, originalName: string, displayName: string) => void
  onAggregationChange?: (dimensionId: string, aggregation: string) => void
  onFormatChange?: (dimensionId: string, format: MetricFormat) => void
  invalidIds?: Set<string>
}
type MetricFormat = {
  type: 'number' | 'percent' | 'duration' | 'storage'
  decimalPlaces: number
  unit?: string
  suffix?: string
  thousandSeparator: boolean
}
export function DimensionBlock({
  isDimension,
  dimensions = [],
  isStack,
  maxDimensions,
  isDragOver = false,
  onDragOver,
  onDragLeave,
  onDrop,
  onDelete,
  onSortChange,
  onEditDisplayName,
  onAggregationChange,
  isMetricCard,
  onFormatChange,
  invalidIds
}: DimensionBlockProps) {
  const { t } = useTranslation("dashboard")

  const [hoveredDimension, setHoveredDimension] = useState<string | null>(null)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [hoveredMenuItem, setHoveredMenuItem] = useState<{
    dimensionId: string
    menuType: 'sort' | 'aggregation' | 'format'
  } | null>(null)
  const [selectedDimensionId, setSelectedDimensionId] = useState<string | null>(null)
  const [editingMetric, setEditingMetric] = useState<DimensionItem | null>(null)
  const [formatDialogOpen, setFormatDialogOpen] = useState(false)
  const [localFormat, setLocalFormat] = useState<MetricFormat | null>(null)
  const [hoveredIcon, setHoveredIcon] = useState<string | null>(null)
  // 获取字段样式
  const getFieldTypeStyle = (dimension: DimensionItem) => {
    const isSelected = selectedDimensionId === dimension.id

    const bgColor = isSelected
      ? dimension.fieldType === 'dimension'
        ? 'bg-blue-100'
        : 'bg-[#E7F8FA]'
      : dimension.fieldType === 'dimension'
        ? 'bg-blue-50'
        : 'bg-[#E7F8FA]'

    const borderColor = dimension.fieldType === 'dimension' ? 'border-blue-300' : 'border-[#88E1EB]'

    const invalidStyle = invalidIds?.has(dimension.id) ? 'border-red-500 bg-red-50' : ''

    return `${bgColor} border ${borderColor} ${invalidStyle} hover:bg-opacity-80 transition-colors`
  }


  // 选项配置
  const isVirtualMetric = (dimension: DimensionItem) => {
    console.log(12312312312312312, dimension);

    return dimension.fieldType === 'metric' && dimension.isVirtual === true;
  };
  const aggregationOptions = [
    { label: t('dimensionBlock.aggregation.sum'), value: 'sum' },
    { label: t('dimensionBlock.aggregation.avg'), value: 'average' },
    { label: t('dimensionBlock.aggregation.max'), value: 'max' },
    { label: t('dimensionBlock.aggregation.min'), value: 'min' },
    { label: t('dimensionBlock.aggregation.count'), value: 'count' },
    { label: t('dimensionBlock.aggregation.distinctCount'), value: 'distinct_count' },
  ]

  const sortOptions = [
    { label: t('dimensionBlock.sort.none'), value: null },
    { label: t('dimensionBlock.sort.asc'), value: 'asc' },
    { label: t('dimensionBlock.sort.desc'), value: 'desc' }
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
        <div className="space-y-2 border rounded-md p-[2px]">
          {dimensions.map((dimension) => (
            <div
              key={dimension.id}
              className="relative group"
              onMouseEnter={() => setHoveredDimension(dimension.id)}
              onMouseLeave={() => setHoveredDimension(null)}
            >
              <div
                className={`
              flex items-center justify-between gap-2 p-1 rounded-md border h-[28px]
              ${getFieldTypeStyle(dimension)}
              ${selectedDimensionId === dimension.id ? (dimension.fieldType === 'dimension' ? 'bg-blue-100' : 'bg-[#E7F8FA]') : ''}
              ${invalidIds?.has(dimension.id) ? 'border-red-500 bg-red-50' : ''}
              hover:bg-opacity-80 transition-colors
            `}
                onClick={() => setSelectedDimensionId(dimension.id)}
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
                      className="h-6 w-6 p-0 hover:bg-transparent"
                      onClick={(e) => handleSettingsClick(dimension.id, e)}
                      onMouseEnter={() => setHoveredIcon(dimension.id)}
                      onMouseLeave={() => setHoveredIcon(null)}
                    >
                      {hoveredIcon === dimension.id || openMenuId === dimension.id ? (
                        <img src="/assets/dashboard/setting.svg" alt="设置" className="h-3 w-3 object-contain" />
                      ) : (
                        <Settings className="h-3 w-3" />
                      )}
                    </Button>

                    {/* 菜单 */}
                    {openMenuId === dimension.id && (
                      <div
                        className="absolute right-full top-0 mr-1 bg-white border rounded-md shadow-lg z-20 p-2 min-w-[120px]"
                        onClick={(e) => e.stopPropagation()}

                      >
                        {/* 维度菜单 */}
                        {dimension.fieldType === 'dimension' ? (
                          <>
                            {/* 排序 */}
                            {isStack !== "stack" &&
                              <>
                                <div className="relative">
                                  <div
                                    className={`flex items-center justify-between px-2 py-1 text-xs rounded cursor-pointer ${hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'sort' ? 'bg-gray-100' : 'hover:bg-gray-100'}`}
                                    onMouseEnter={() => handleMenuItemHover(dimension.id, 'sort')}
                                  >
                                    <span>{t('dimensionBlock.menu.sort')}</span>
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
                                            onSortChange?.(dimension.id, option.value as null | 'asc' | 'desc')
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
                              </>
                            }

                            {/* 编辑显示名称 */}
                            <button
                              className="block w-full text-left px-2 py-1 text-xs hover:bg-gray-100 rounded"
                              onMouseEnter={() => {
                                setHoveredMenuItem(null);
                              }}
                              onClick={() => {
                                onEditDisplayName(dimension.id, dimension.originalName, dimension.displayName)
                                setOpenMenuId(null)
                              }}
                            >
                              {t('componentConfigDrawer.dialog.editDisplayName')}
                            </button>
                          </>
                        ) : (
                          <>
                            {/* 指标菜单 */}
                            {/* 汇总方式 */}

                            {!isVirtualMetric(dimension) && dimension.fieldType === 'metric' && <div className="relative">
                              <div
                                className={`flex items-center justify-between px-2 py-1 text-xs rounded cursor-pointer ${hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'aggregation' ? 'bg-gray-100' : 'hover:bg-gray-100'}`}
                                onMouseEnter={() => handleMenuItemHover(dimension.id, 'aggregation')}
                              >
                                <span>{t('dimensionBlock.menu.aggregation')}</span>
                                <ChevronRight className="h-3 w-3" />
                              </div>

                              {/* 汇总方式子菜单 */}
                              {hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'aggregation' && (
                                <div
                                  className="absolute left-full top-0 ml-1 bg-white border rounded-md shadow-lg z-30 p-2 min-w-[90px]"
                                  onMouseEnter={() => handleMenuItemHover(dimension.id, 'aggregation')}
                                  onMouseLeave={() => setHoveredMenuItem(null)}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    e.preventDefault();
                                  }}
                                >
                                  {aggregationOptions.map((option) => (
                                    <button
                                      key={option.value}
                                      className={`flex items-center justify-between w-full px-2 py-1 text-xs rounded ${dimension.aggregation === option.value ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100'}`}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        e.preventDefault();
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
                            </div>}

                            {/* 排序  //指标卡不显示排序*/}


                            {isMetricCard && <div className="relative mt-1">
                              <div
                                className={`flex items-center justify-between px-2 py-1 text-xs rounded cursor-pointer ${hoveredMenuItem?.dimensionId === dimension.id && hoveredMenuItem?.menuType === 'sort' ? 'bg-gray-100' : 'hover:bg-gray-100'}`}
                                onMouseEnter={() => handleMenuItemHover(dimension.id, 'sort')}
                              >
                                <span>{t('dimensionBlock.menu.sort')}</span>
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
                            </div>}

                            {/* 数值格式 */}
                            <button
                              className="flex items-center justify-between w-full px-2 py-1 text-xs rounded hover:bg-gray-100"
                              onMouseEnter={() => {
                                setHoveredMenuItem(null);
                              }}
                              onClick={() => {
                                setEditingMetric(dimension)
                                setLocalFormat(
                                  dimension.numberFormat || {
                                    type: 'number',
                                    decimalPlaces: 0,
                                    unit: '',
                                    suffix: '',
                                    thousandSeparator: false
                                  }
                                )
                                setFormatDialogOpen(true)
                                setOpenMenuId(null)
                              }}
                            >
                              <span>{t('dimensionBlock.menu.format')}</span>
                            </button>


                            <div className="h-px bg-gray-200 my-1"></div>

                            {/* 编辑显示名称 */}
                            <button
                              className="block w-full text-left px-2 py-1 text-xs hover:bg-gray-100 rounded"
                              onMouseEnter={() => {
                                setHoveredMenuItem(null);
                              }}
                              onClick={() => {
                                onEditDisplayName(dimension.id, dimension.originalName, dimension.displayName)
                                setOpenMenuId(null)
                              }}
                            >
                              {t('componentConfigDrawer.dialog.editDisplayName')}
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
                    title={t('dimensionBlock.button.deleteField')}
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
            {isDimension
              ? t('dimensionBlock.prompt.dragDimensionHere')
              : t('dimensionBlock.prompt.dragMetricHere')}
          </div>
        </div>
      )}
      {editingMetric && localFormat && (
        <Dialog
          open={formatDialogOpen}
          onOpenChange={(open) => {
            setFormatDialogOpen(open)
            if (!open) {
              setEditingMetric(null)
              setLocalFormat(null)
            }
          }}
        >
          <DialogContent className="sm:max-w-[520px]">
            <DialogHeader>
              <DialogTitle>{t('dimensionBlock.dialog.formatTitle')}</DialogTitle>
            </DialogHeader>

            <div className="space-y-6 py-4">
              {/* 格式类型 */}
              <div>
                <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.formatType')}</div>
                <RadioGroup
                  value={localFormat.type}
                  onValueChange={(value) =>
                    setLocalFormat({
                      ...localFormat,
                      type: value as any,
                      unit: value === 'percent' ? undefined : localFormat.unit,
                      thousandSeparator: value === 'percent' ? false : localFormat.thousandSeparator
                    })
                  }
                  className="flex gap-6"
                >
                  {[
                    { label: t('dimensionBlock.dialog.formatTypes.number'), value: 'number' },
                    { label: t('dimensionBlock.dialog.formatTypes.percent'), value: 'percent' },
                    { label: t('dimensionBlock.dialog.formatTypes.duration'), value: 'duration' },
                    { label: t('dimensionBlock.dialog.formatTypes.storage'), value: 'storage' }
                  ].map(item => (
                    <div key={item.value} className="flex items-center space-x-2">
                      <RadioGroupItem value={item.value} id={`format-${item.value}`} />
                      <Label htmlFor={`format-${item.value}`} className="text-sm cursor-pointer">
                        {item.label}
                      </Label>
                    </div>
                  ))}
                </RadioGroup>
              </div>

              {/* 小数位数 - 默认0，上限5 */}
              <div>
                <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.decimalPlaces')}</div>
                <Input
                  type="number"
                  min={0}
                  max={5}
                  step={1}
                  value={localFormat.decimalPlaces}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    if (val >= 0 && val <= 5) {
                      setLocalFormat({ ...localFormat, decimalPlaces: val })
                    }
                  }}
                  className="w-full"
                />
              </div>

              {/* 百分比 隐藏 单位+千分符；其他格式正常显示 */}
              {localFormat.type !== 'percent' && (
                <>
                  {/* 单位 - 不同格式对应不同下拉选项 */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.unit')}</div>
                      <Select
                        value={localFormat.unit ||
                          (localFormat.type === 'storage' ? 'B' :
                            localFormat.type === 'duration' ? 'ms' :
                              'none')}
                        onValueChange={(value) => {
                          let unitVal = value === "none" ? "" : value;
                          setLocalFormat({ ...localFormat, unit: unitVal })
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={t('dimensionBlock.dialog.selectUnit')} />
                        </SelectTrigger>
                        <SelectContent>
                          {localFormat.type === 'number' && (
                            <>
                              <SelectItem value="none">{t('dimensionBlock.dialog.none')}</SelectItem>
                              <SelectItem value="Thousand">Thousand (K)</SelectItem>
                              <SelectItem value="Million">Million (M)</SelectItem>
                              <SelectItem value="Billion">Billion (B)</SelectItem>
                            </>
                          )}
                          {localFormat.type === 'duration' && (
                            <>
                              <SelectItem value="ms">ms</SelectItem>
                              <SelectItem value="s">s</SelectItem>
                              <SelectItem value="min">min</SelectItem>
                              <SelectItem value="hour">hour</SelectItem>
                            </>
                          )}
                          {localFormat.type === 'storage' && (
                            <>
                              <SelectItem value="B">B</SelectItem>
                              <SelectItem value="KB">KB</SelectItem>
                              <SelectItem value="MB">MB</SelectItem>
                              <SelectItem value="GB">GB</SelectItem>
                              <SelectItem value="TB">TB</SelectItem>
                            </>
                          )}
                        </SelectContent>
                      </Select>
                    </div>

                    <div>
                      <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.suffix')}</div>
                      <Input
                        placeholder={t('dimensionBlock.dialog.enterSuffix')}
                        value={localFormat.suffix || ""}
                        onChange={(e) =>
                          setLocalFormat({ ...localFormat, suffix: e.target.value })
                        }
                        className="w-full"
                      />
                    </div>
                  </div>

                  {/* 千分符 */}
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={localFormat.thousandSeparator}
                      onCheckedChange={(checked) =>
                        setLocalFormat({
                          ...localFormat,
                          thousandSeparator: checked as boolean
                        })
                      }
                      id="thousand-separator"
                    />
                    <label htmlFor="thousand-separator" className="text-sm cursor-pointer">
                      {t('dimensionBlock.dialog.thousandSeparator')}
                    </label>
                  </div>
                </>
              )}

              {/* 百分比 只显示后缀输入框 */}
              {localFormat.type === 'percent' && (
                <div>
                  <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.suffix')}</div>
                  <Input
                    placeholder={t('dimensionBlock.dialog.enterSuffix')}
                    value={localFormat.suffix || ""}
                    onChange={(e) =>
                      setLocalFormat({ ...localFormat, suffix: e.target.value })
                    }
                    className="w-full"
                  />
                </div>
              )}

              {/* 示例 - 匹配需求默认示例 */}
              <div className="text-sm text-muted-foreground">
                {t('dimensionBlock.dialog.example')}: {
                  localFormat.type === 'percent' ? '99%' :
                    localFormat.type === 'duration' ? '2000000' :
                      localFormat.type === 'storage' ? '2000000' : '20000'
                }
              </div>
            </div>

            {/* Footer */}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setFormatDialogOpen(false)
                  setEditingMetric(null)
                  setLocalFormat(null)
                }}
              >
                {t('chartSelector.buttons.cancel')}
              </Button>
              <Button
                onClick={() => {
                  if (!editingMetric || !localFormat) return

                  const formatToSave: MetricFormat = {
                    type: localFormat.type,
                    decimalPlaces: localFormat.decimalPlaces,
                    thousandSeparator: localFormat.type === 'percent' ? false : localFormat.thousandSeparator,
                    unit: localFormat.type === 'percent' ? undefined : (localFormat.unit === "" ? undefined : localFormat.unit),
                    suffix: localFormat.suffix === "" ? undefined : localFormat.suffix
                  }

                  onFormatChange?.(editingMetric.id, formatToSave)
                  setFormatDialogOpen(false)
                  setEditingMetric(null)
                  setLocalFormat(null)
                }}
              >
                {t('chartSelector.buttons.save')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}