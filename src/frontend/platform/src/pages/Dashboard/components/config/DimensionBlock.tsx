"use client"

import { useState } from "react"
import { Button } from "@/components/bs-ui/button"
import { Settings, X, Check } from "lucide-react"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio"
import { Label } from "@/components/bs-ui/label"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { useTranslation } from "react-i18next"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/bs-ui/dropdownMenu"

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
  isVirtual?: boolean // 补充定义
  fieldId?: string
  timeGranularity?: string
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

  // const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  // const [hoveredMenuItem, setHoveredMenuItem] = useState<...>...

  const [selectedDimensionId, setSelectedDimensionId] = useState<string | null>(null)
  const [editingMetric, setEditingMetric] = useState<DimensionItem | null>(null)
  const [formatDialogOpen, setFormatDialogOpen] = useState(false)
  const [localFormat, setLocalFormat] = useState<MetricFormat | null>(null)
  const [hoveredIcon, setHoveredIcon] = useState<string | null>(null)

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
              draggable={dimension.fieldType === 'dimension'}
              onDragStart={(e) => {
                if (dimension.fieldType !== 'dimension') return
                e.stopPropagation()
                e.dataTransfer.effectAllowed = 'move'
                const dragData = {
                  id: dimension.id,
                  fieldId: dimension.fieldId,
                  name: dimension.name,
                  displayName: dimension.displayName || dimension.name,
                  originalName: dimension.originalName || dimension.name,
                  fieldType: dimension.fieldType,
                  timeGranularity: dimension.timeGranularity || null,
                  isExistingDimension: true,
                  sourceSection: isStack === 'stack' ? 'stack' : 'category'
                }
                e.dataTransfer.setData('application/json', JSON.stringify(dragData))
              }}
              className={`relative group ${dimension.fieldType === 'dimension' ? 'cursor-move' : 'cursor-default'}`}
              onMouseEnter={() => setHoveredDimension(dimension.id)}
              onMouseLeave={() => setHoveredDimension(null)}
            >
              <div
                className={`
                  flex items-center justify-between gap-2 p-1 rounded-md border h-[28px]
                  ${getFieldTypeStyle(dimension)}
                `}
                onClick={() => setSelectedDimensionId(dimension.id)}
              >

                {/* 字段名称 */}
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-medium truncate">
                    {dimension.displayName && dimension.displayName.length > 15
                      ? `${dimension.displayName.substring(0, 15)}...`
                      : dimension.displayName}
                  </span>
                </div>

                {/* 操作按钮区域 */}
                <div className={`flex items-center gap-1 ${hoveredDimension === dimension.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 transition-opacity'}`}>

                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 p-0 hover:bg-transparent data-[state=open]:opacity-100"
                        onMouseEnter={() => setHoveredIcon(dimension.id)}
                        onMouseLeave={() => setHoveredIcon(null)}
                        onClick={(e) => e.stopPropagation()} // 防止触发父级选中
                      >
                        {hoveredIcon === dimension.id ? (
                          <img src="/assets/dashboard/setting.svg" alt="设置" className="h-3 w-3 object-contain" />
                        ) : (
                          <Settings className="h-3 w-3" />
                        )}
                      </Button>
                    </DropdownMenuTrigger>

                    <DropdownMenuContent
                      className="w-40"
                      align="start"
                      side="right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {/* --- 维度菜单 --- */}
                      {dimension.fieldType === 'dimension' && (
                        <>
                          {/* 排序级联菜单 */}
                          {isStack !== "stack" && (
                            <DropdownMenuSub>
                              <DropdownMenuSubTrigger>
                                <span>{t('dimensionBlock.menu.sort')}</span>
                              </DropdownMenuSubTrigger>
                              <DropdownMenuPortal>
                                <DropdownMenuSubContent>
                                  {sortOptions.map((option) => (
                                    <DropdownMenuItem
                                      key={option.value || 'null'}
                                      onClick={() => onSortChange?.(dimension.id, option.value as any)}
                                      className="justify-between"
                                    >
                                      {option.label}
                                      {dimension.sort === option.value && <Check className="h-4 w-4" />}
                                    </DropdownMenuItem>
                                  ))}
                                </DropdownMenuSubContent>
                              </DropdownMenuPortal>
                            </DropdownMenuSub>
                          )}

                          {isStack !== "stack" && <DropdownMenuSeparator />}

                          <DropdownMenuItem
                            onClick={() => onEditDisplayName(dimension.id, dimension.originalName, dimension.displayName)}
                          >
                            {t('componentConfigDrawer.dialog.editDisplayName')}
                          </DropdownMenuItem>
                        </>
                      )}

                      {/* --- 指标菜单 --- */}
                      {dimension.fieldType === 'metric' && (
                        <>
                          {/* 聚合方式级联菜单 */}
                          {!isVirtualMetric(dimension) && (
                            <DropdownMenuSub>
                              <DropdownMenuSubTrigger>
                                <span>{t('dimensionBlock.menu.aggregation')}</span>
                              </DropdownMenuSubTrigger>
                              <DropdownMenuPortal>
                                <DropdownMenuSubContent>
                                  {aggregationOptions.map((option) => (
                                    <DropdownMenuItem
                                      key={option.value}
                                      onClick={() => onAggregationChange?.(dimension.id, option.value)}
                                      className="justify-between"
                                    >
                                      {option.label}
                                      {dimension.aggregation === option.value && <Check className="h-4 w-4" />}
                                    </DropdownMenuItem>
                                  ))}
                                </DropdownMenuSubContent>
                              </DropdownMenuPortal>
                            </DropdownMenuSub>
                          )}

                          {/* 指标排序级联菜单 */}
                          {isMetricCard && (
                            <DropdownMenuSub>
                              <DropdownMenuSubTrigger>
                                <span>{t('dimensionBlock.menu.sort')}</span>
                              </DropdownMenuSubTrigger>
                              <DropdownMenuPortal>
                                <DropdownMenuSubContent>
                                  {sortOptions.map((option) => (
                                    <DropdownMenuItem
                                      key={option.value || 'null'}
                                      onClick={() => onSortChange?.(dimension.id, option.value as any)}
                                      className="justify-between"
                                    >
                                      {option.label}
                                      {dimension.sort === option.value && <Check className="h-4 w-4" />}
                                    </DropdownMenuItem>
                                  ))}
                                </DropdownMenuSubContent>
                              </DropdownMenuPortal>
                            </DropdownMenuSub>
                          )}

                          {/* 数值格式 */}
                          <DropdownMenuItem
                            onClick={() => {
                              setEditingMetric(dimension)
                              setLocalFormat(
                                dimension.numberFormat || {
                                  type: 'number',
                                  decimalPlaces: 2,
                                  unit: '',
                                  suffix: '',
                                  thousandSeparator: false
                                }
                              )
                              setFormatDialogOpen(true)
                            }}
                          >
                            {t('dimensionBlock.menu.format')}
                          </DropdownMenuItem>

                          <DropdownMenuSeparator />

                          {/* 编辑显示名称 */}
                          <DropdownMenuItem
                            onClick={() => onEditDisplayName(dimension.id, dimension.originalName, dimension.displayName)}
                          >
                            {t('componentConfigDrawer.dialog.editDisplayName')}
                          </DropdownMenuItem>
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>

                  {/* 删除按钮 */}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 p-0 hover:bg-red-200"
                    onClick={(e) => {
                      e.stopPropagation(); // 防止拖拽或选中
                      onDelete(dimension.id);
                    }}
                    title={t('dimensionBlock.button.deleteField')}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              </div>
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
              <div>
                <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.formatType')}</div>
                {/* ... RadioGroup ... */}
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
                  type="number" min={0} max={5} step={1}
                  value={localFormat.decimalPlaces}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val === '') {
                      setLocalFormat({ ...localFormat, decimalPlaces: undefined })
                    } else {
                      const numVal = Number(val);
                      if (numVal >= 0 && numVal <= 5) {
                        setLocalFormat({ ...localFormat, decimalPlaces: numVal })
                      }
                    }
                  }}
                  onBlur={(e) => {
                    const val = e.target.value;
                    if (val === '' || isNaN(Number(val))) {
                      setLocalFormat({ ...localFormat, decimalPlaces: 2 })
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
                          {/* Select Items Logic */}
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
              <Button variant="outline" onClick={() => {
                setFormatDialogOpen(false)
                setEditingMetric(null)
                setLocalFormat(null)
              }}>
                {t('chartSelector.buttons.cancel')}
              </Button>
              <Button onClick={() => {
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
              }}>
                {t('chartSelector.buttons.save')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}