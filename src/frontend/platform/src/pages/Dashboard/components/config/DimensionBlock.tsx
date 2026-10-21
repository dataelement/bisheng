// @ts-strict-ignore
import { Button } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";


import { useEffect,useState } from "react";
import { MetricFormatDialog } from "./MetricFormatDialog";

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
} from "@/components/bs-ui/dropdownMenu";
import { useTranslation } from "react-i18next";

export interface DimensionItem {
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
  isDivide?: string
}

interface DimensionBlockProps {
  isStack?: string;
  isMetricCard?: boolean;
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

export type MetricFormat = {
  type: 'number' | 'percent' | 'duration' | 'storage'
  decimalPlaces?: number
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
  // 监听editingMetric变化，设置默认格式
  useEffect(() => {
    if (editingMetric) {
      console.log('Editing metric:', editingMetric);

      const currentFormat = editingMetric.numberFormat;

      if (currentFormat) {
        console.log('使用现有的 numberFormat:', currentFormat);
        const defaultDecimal = currentFormat.type === 'number' ? 0 : 2;
        setLocalFormat({
          type: currentFormat.type,
          decimalPlaces: currentFormat.decimalPlaces ?? defaultDecimal,
          unit: currentFormat.unit || '',
          suffix: currentFormat.suffix || '',
          thousandSeparator: currentFormat.thousandSeparator || false
        });
      } else {
        const defaultFormat: MetricFormat = editingMetric.isDivide === "divide"
          ? {
            type: 'percent',
            decimalPlaces: 2,
            thousandSeparator: false,
            unit: undefined,
            suffix: ''
          }
          : {
            type: 'number',
            decimalPlaces: 0,
            thousandSeparator: false,
            unit: '',
            suffix: ''
          };
        setLocalFormat(defaultFormat);
      }
    }
  }, [editingMetric]);
  const getFieldTypeStyle = (dimension: DimensionItem) => {
  const isSelected = selectedDimensionId === dimension.id

  //  (Blue)
  const dimensionStyle = isSelected
    ? 'bg-blue-100 border-blue-300 dark:bg-blue-900/40 dark:border-blue-700'
    : 'bg-blue-50 border-blue-300 dark:bg-blue-900/20 dark:border-blue-800'

  // (Cyan/Teal)
  const measureStyle = isSelected
    ? 'bg-[#E7F8FA] border-[#88E1EB] dark:bg-cyan-950/50 dark:border-cyan-700'
    : 'bg-[#E7F8FA] border-[#88E1EB] dark:bg-cyan-950/30 dark:border-cyan-800'

  // error
  const invalidStyle = invalidIds?.has(dimension.id)
    ? 'border-red-500 bg-red-50 dark:border-red-700 dark:bg-red-900/30'
    : ''

  const baseColor = dimension.fieldType === 'dimension' ? dimensionStyle : measureStyle

  return `${baseColor} border ${invalidStyle} hover:bg-opacity-80 transition-colors`
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
                      <Button variant="text" size="medium" className="h-6 w-6 p-0 hover:bg-transparent data-[state=open]:opacity-100" aria-label={t("settings")} onMouseEnter={() => setHoveredIcon(dimension.id)} onMouseLeave={() => setHoveredIcon(null)} onClick={(e) => e.stopPropagation()} color="default" iconOnly>
                        <Outlined.Setting size={14} />
                      </Button>
                    </DropdownMenuTrigger>

                    <DropdownMenuContent
                      className="w-40"
                      align="start"
                      side="left"
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
                                      {dimension.sort === option.value && <Outlined.Check className="h-4 w-4" />}
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
                                      {dimension.aggregation === option.value && <Outlined.Check className="h-4 w-4" />}
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
                                      {dimension.sort === option.value && <Outlined.Check className="h-4 w-4" />}
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
                  <Button variant="text" size="medium" className="h-6 w-6 p-0 hover:bg-red-200" onClick={(e) => {
                      e.stopPropagation(); // 防止拖拽或选中
                      onDelete(dimension.id);
                    }} title={t('dimensionBlock.button.deleteField')} color="default" iconOnly>
                    <Outlined.Close className="h-3 w-3" />
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
<MetricFormatDialog {...{formatDialogOpen,setFormatDialogOpen,editingMetric,setEditingMetric,localFormat,setLocalFormat,onFormatChange}} />
      )}
    </div>
  )
}