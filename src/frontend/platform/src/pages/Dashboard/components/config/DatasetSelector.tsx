"use client"

import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { getDatasets, MetricConfig } from "@/controllers/API/dashboard"
import { Calendar, ChevronDown, ChevronRight, ChevronUp, Clock3, Hash, Search, Type } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useQuery } from "react-query"
import { useTranslation } from "react-i18next"

export interface DatasetField {
    fieldId?: string
    fieldCode: string          // 真正用来过滤 / SQL
    fieldName?: string
    displayName: string        // UI 显示
    fieldType: "string" | "number" | "date"
    role: "dimension" | "metric"
    enumValues?: string[]
    isVirtual?: boolean
    isDivide?: string
    numberFormat?: MetricConfig["default_number_format"]
    timeGranularity?: string
}

interface DatasetSelectorProps {
    selectedDatasetCode?: string
    onDatasetChange?: (datasetCode: string) => void
    onDragStart?: (e: React.DragEvent, data: any) => void
    onFieldsLoaded?: (fields: DatasetField[]) => void
    onFieldClick?: (field: DatasetField) => void
}

const TIME_ICONS: Record<string, JSX.Element> = {
    year: <Clock3 color="#1d78ff" size={14} />,
    quarter: <Clock3 color="#1d78ff" size={14} />,
    month: <Clock3 color="#1d78ff" size={14} />,
    week: <Clock3 color="#1d78ff" size={14} />,
    day: <Clock3 color="#1d78ff" size={14} />,
    hour: <Clock3 color="#1d78ff" size={14} />,
}

const getFieldTypeIcon = (type: 'string' | 'number' | 'date') => {
    switch (type) {
        case 'date':
            return <Calendar className="h-4 w-4 text-blue-500" />
        case 'number':
            return <Hash className="h-4 w-4 text-blue-500" />
        case 'string':
            return <Type className="h-4 w-4 text-blue-500" />
    }
}

// 判断是否为虚拟指标
const isVirtualMetric = (metric: MetricConfig): boolean => {

    return Boolean(metric.is_virtual)
}

export function createMetricDatasetField(metric: MetricConfig, displayName: string): DatasetField {
    return {
        fieldCode: metric.field,
        fieldId: metric.field,
        displayName,
        fieldType: metric.field_type,
        isVirtual: metric.is_virtual,
        isDivide: metric.formula,
        numberFormat: metric.default_number_format,
        role: "metric",
    }
}

export function DatasetSelector({ selectedDatasetCode, isMetricCard, onDatasetChange, onDragStart, onFieldsLoaded, onFieldClick }: DatasetSelectorProps) {
    const { t } = useTranslation("dashboard")
    const [searchTerm, setSearchTerm] = useState("")
    const [dimensionsExpanded, setDimensionsExpanded] = useState(true)
    const [metricsExpanded, setMetricsExpanded] = useState(true)
    const [timeExpandedMap, setTimeExpandedMap] = useState<Record<string, boolean>>({})

    // 获取数据集列表
    const { data: allDatasets = [], isLoading: datasetsLoading } = useQuery({
        queryKey: ['datasets'],
        queryFn: () => getDatasets()
    })

    // 前端搜索过滤
    const filteredDatasets = useMemo(() => {
        if (!searchTerm) return allDatasets
        const searchLower = searchTerm.toLowerCase()
        return allDatasets.filter(d => {
            const localizedName = t(d.dataset_code, {
                defaultValue: d.dataset_name
            }).toLowerCase()
            return localizedName.includes(searchLower) ||
                d.dataset_name.toLowerCase().includes(searchLower) ||
                d.dataset_code.toLowerCase().includes(searchLower) ||
                (d.description && d.description.toLowerCase().includes(searchLower))
        })
    }, [allDatasets, searchTerm, t])
    // 获取选中的数据集详情
    const selectedDataset = useMemo(() => {
        return allDatasets.find(d => d.dataset_code === selectedDatasetCode)
    }, [allDatasets, selectedDatasetCode])

    // F058 AC-07: datasets sharing a non-null dataset_group render as one grouped
    // section (e.g. 用户规模统计/活跃用户规模统计/全员每日参与度 -> "用户数据统计") instead of
    // separate top-level entries. Ungrouped datasets keep their original flat listing.
    const { groupedSections, ungroupedDatasets } = useMemo(() => {
        const sections = new Map<string, typeof filteredDatasets>()
        const ungrouped: typeof filteredDatasets = []
        filteredDatasets.forEach(dataset => {
            if (dataset.dataset_group) {
                if (!sections.has(dataset.dataset_group)) sections.set(dataset.dataset_group, [])
                sections.get(dataset.dataset_group)!.push(dataset)
            } else {
                ungrouped.push(dataset)
            }
        })
        return { groupedSections: sections, ungroupedDatasets: ungrouped }
    }, [filteredDatasets])

    // 处理拖拽开始
    const handleDragStart = (e: React.DragEvent, data: any, fieldType: 'dimension' | 'metric') => {
        e.dataTransfer.effectAllowed = 'copy'
        const dragData = {
            id: data.fieldCode,
            name: data.displayName,
            displayName: data.displayName,
            fieldId: data.fieldId,
            fieldCode: data.fieldCode,
            fieldType,
            isDivide: data.isDivide,
            numberFormat: data.numberFormat,
            timeGranularity: data.timeGranularity,
        }

        e.dataTransfer.setData('application/json', JSON.stringify(dragData))
        if (onDragStart) {
            onDragStart(e, dragData)
        }
    }

    const toggleTimeExpanded = (field: string) => {
        setTimeExpandedMap(prev => ({ ...prev, [field]: !prev[field] }))
    }

    const datasetFields = useMemo<DatasetField[]>(() => {
        if (!selectedDataset) return []

        const dimensions = selectedDataset.schema_config.dimensions.map(d => ({
            fieldCode: d.field,
            fieldId: d.field,
            displayName: t(d.field, { defaultValue: d.name }),
            fieldType: d.field_type,
            role: "dimension" as const
        }))

        const metrics = selectedDataset.schema_config.metrics.map(m => createMetricDatasetField(
            m,
            t(m.field, { defaultValue: m.name }),
        ))

        return [...dimensions, ...metrics]
    }, [selectedDataset, t])

    useEffect(() => {
        if (selectedDataset && onFieldsLoaded) {
            onFieldsLoaded(datasetFields)
        }
    }, [datasetFields, onFieldsLoaded, selectedDataset])

    const getTimeGranularityLabel = (granularity: string): string => {
        return t(`datasetSelector.timeGranularity.${granularity}`)
    }

    return (
        <div className="flex flex-col h-full">
            {/* 数据集选择 */}
            <div className="p-4 border-b">
                <Label className="text-sm font-medium mb-2 block">
                    {t("datasetSelector.dataset")}
                </Label>
                <Select value={selectedDatasetCode} onValueChange={onDatasetChange}>
                    <SelectTrigger className="w-full">
                        <SelectValue placeholder={t("datasetSelector.selectDataset")} />
                    </SelectTrigger>
                    <SelectContent>
                        {/* 搜索框 */}
                        <div className="px-2 py-1.5">
                            <div className="relative">
                                <Search className="absolute left-2 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground z-10" />
                                <Input
                                    placeholder={t("datasetSelector.searchDataset")}
                                    value={searchTerm}
                                    onChange={(e) => setSearchTerm(e.target.value)}
                                    className="pl-8 h-8"
                                    onClick={(e) => e.stopPropagation()}
                                />
                            </div>
                        </div>
                        {/* 数据集列表 */}
                        {datasetsLoading ? (
                            <div className="px-2 py-4 text-sm text-muted-foreground text-center">
                                {t("datasetSelector.loading")}
                            </div>
                        ) : filteredDatasets.length === 0 ? (
                            <div className="px-2 py-4 text-sm text-muted-foreground text-center">
                                {t("datasetSelector.noDatasetsFound")}
                            </div>
                        ) : (
                            <>
                                {Array.from(groupedSections.entries()).map(([groupKey, datasets]) => (
                                    <SelectGroup key={groupKey}>
                                        <SelectLabel>
                                            {t(`datasetSelector.group.${groupKey}`, { defaultValue: groupKey })}
                                        </SelectLabel>
                                        {datasets.map((dataset) => (
                                            <SelectItem key={dataset.dataset_code} value={dataset.dataset_code}>
                                                {t(dataset.dataset_code, {
                                                    defaultValue: dataset.dataset_name
                                                })}
                                            </SelectItem>
                                        ))}
                                    </SelectGroup>
                                ))}
                                {ungroupedDatasets.map((dataset) => (
                                    <SelectItem key={dataset.dataset_code} value={dataset.dataset_code}>
                                        {t(dataset.dataset_code, {
                                            defaultValue: dataset.dataset_name
                                        })}
                                    </SelectItem>
                                ))}
                            </>
                        )}
                    </SelectContent>
                </Select>
            </div>

            {/* 字段展示区域 */}
            {selectedDataset && (
                <div className="flex-1 flex flex-col min-h-0">
                    {!isMetricCard && (
                        <div className="flex-1 flex flex-col min-h-0 border-b">
                            <button
                                className="w-full px-4 py-3 flex items-center justify-between hover:bg-accent/50 transition-colors shrink-0"
                                onClick={() => setDimensionsExpanded(!dimensionsExpanded)}
                            >
                                <span className="text-sm font-medium">{t("datasetSelector.dimensions")}</span>
                                {dimensionsExpanded ? (
                                    <ChevronDown className="h-4 w-4" />
                                ) : (
                                    <ChevronUp className="h-4 w-4" />
                                )}
                            </button>

                            {dimensionsExpanded && (
                                <div className="flex-1 overflow-y-auto px-4 pb-2 space-y-0 min-h-0">
                                    {selectedDataset.schema_config.dimensions.map((dimension) => {
                                        if (dimension.time_granularitys && dimension.time_granularitys.length > 0) {
                                            return dimension.time_granularitys.map((g) => {
                                                const displayName = t(`${dimension.field}.${g}`, {
                                                    defaultValue: `${dimension.name}(${getTimeGranularityLabel(g)})`
                                                })
                                                const field: DatasetField = {
                                                    fieldCode: dimension.field,
                                                    displayName,
                                                    fieldType: "date",
                                                    role: "dimension",
                                                    timeGranularity: g,
                                                }
                                                return (
                                                    <div
                                                        key={dimension.field + g}
                                                        className="flex items-center gap-2 p-2 rounded hover:bg-accent/30 cursor-move transition-colors"
                                                        draggable
                                                        onDragStart={(e) => handleDragStart(e, field, 'dimension')}
                                                        onClick={(e) => { e.stopPropagation(); onFieldClick?.(field) }}
                                                    >
                                                        {TIME_ICONS[g]}
                                                        <span className="text-sm flex-1">
                                                            {displayName}
                                                        </span>
                                                    </div>
                                                )
                                            })
                                        }

                                        // 普通非时间字段
                                        const field: DatasetField = {
                                            fieldCode: dimension.field,
                                            displayName: t(dimension.field, {
                                                defaultValue: dimension.name
                                            }),
                                            fieldType: dimension.field_type,
                                            role: "dimension",
                                        }

                                        return (
                                            <div
                                                key={dimension.field}
                                                className="flex items-center gap-2 p-2 rounded hover:bg-accent/30 cursor-move transition-colors"
                                                draggable
                                                onDragStart={(e) => handleDragStart(e, field, 'dimension')}
                                                onClick={(e) => { e.stopPropagation(); onFieldClick?.(field) }}
                                            >
                                                {getFieldTypeIcon(field.fieldType)}
                                                <span className="text-sm flex-1">{field.displayName}</span>
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    )}

                    {/* 指标区域 - 占据下半部分 */}
                    <div className="flex-1 flex flex-col min-h-0">
                        <button
                            className="w-full px-4 py-3 flex items-center justify-between hover:bg-accent/50 transition-colors shrink-0"
                            onClick={() => setMetricsExpanded(!metricsExpanded)}
                        >
                            <span className="text-sm font-medium">{t("datasetSelector.metrics")}</span>
                            {metricsExpanded ? (
                                <ChevronDown className="h-4 w-4" />
                            ) : (
                                <ChevronUp className="h-4 w-4" />
                            )}
                        </button>

                        {metricsExpanded && (
                            <div className="flex-1 overflow-y-auto px-4 pb-3 space-y-2 min-h-0">
                                {selectedDataset.schema_config.metrics.map((metric, index) => {
                                    const isVirtual = isVirtualMetric(metric)
                                    const field = createMetricDatasetField(
                                        metric,
                                        t(metric.field, { defaultValue: metric.name }),
                                    )
                                    return (
                                        <div
                                            key={index}
                                            className="flex items-center gap-2 p-2 rounded hover:bg-accent/30 cursor-move transition-colors"
                                            draggable
                                            onDragStart={(e) => handleDragStart(e, field, 'metric')}
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                onFieldClick?.(field)
                                            }}
                                        >
                                            <div className="text-[#37D6E7]">
                                                <Hash className="h-4 w-4" />
                                            </div>
                                            <span className="text-sm flex-1 flex items-center gap-1">
                                                {field.displayName}
                                                {isVirtual && <span className="text-muted-foreground text-xs">{t("datasetSelector.virtualMetric")}</span>}
                                            </span>
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* 未选择数据集时的提示 */}
            {!selectedDataset && (
                <div className="flex-1 flex items-center justify-center p-4">
                    <p className="text-sm text-muted-foreground text-center">
                        {t("datasetSelector.selectDatasetPrompt")}
                    </p>
                </div>
            )}
        </div>
    )
}
