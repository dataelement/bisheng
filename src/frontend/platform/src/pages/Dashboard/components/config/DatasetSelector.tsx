// @ts-strict-ignore
import { Button, Select, type SelectOption } from '@bisheng/ui';

import { Outlined } from "bisheng-icons";


import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { getDatasets,MetricConfig } from "@/controllers/API/dashboard";
import { Hash,Type } from "lucide-react";
import { useEffect,useMemo,useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "react-query";

export interface DatasetField {
    fieldCode: string          // 真正用来过滤 / SQL
    displayName: string        // UI 显示
    fieldType: "string" | "number" | "date"
    role: "dimension" | "metric"
    enumValues?: string[]
    isVirtual?: boolean
    timeGranularity?: string
}

interface DatasetSelectorProps {
    isMetricCard?: boolean;
    selectedDatasetCode?: string
    onDatasetChange?: (datasetCode: string) => void
    onDragStart?: (e: React.DragEvent, data: any) => void
    onFieldsLoaded?: (fields: DatasetField[]) => void
    onFieldClick?: (field: DatasetField) => void
}

const TIME_ICONS: Record<string, JSX.Element> = {
    year: <Outlined.Time color="#1d78ff" size={14} />,
    quarter: <Outlined.Time color="#1d78ff" size={14} />,
    month: <Outlined.Time color="#1d78ff" size={14} />,
    week: <Outlined.Time color="#1d78ff" size={14} />,
    day: <Outlined.Time color="#1d78ff" size={14} />,
    hour: <Outlined.Time color="#1d78ff" size={14} />,
}

const getFieldTypeIcon = (type: 'string' | 'number' | 'date') => {
    switch (type) {
        case 'date':
            return <Outlined.Calendar className="h-4 w-4 text-blue-500" />
        case 'number':
            return <Hash className="h-4 w-4 text-blue-500" />
        case 'string':
            return <Type className="h-4 w-4 text-blue-500" />
    }
}

// 判断是否为虚拟指标
const isVirtualMetric = (metric: MetricConfig): boolean => {

    return metric.is_virtual
}

export function DatasetSelector({ selectedDatasetCode, isMetricCard, onDatasetChange, onDragStart, onFieldsLoaded, onFieldClick }: DatasetSelectorProps) {
    const { t } = useTranslation("dashboard")
    const selectLabels = useSelectLabels()
    const [dimensionsExpanded, setDimensionsExpanded] = useState(true)
    const [metricsExpanded, setMetricsExpanded] = useState(true)
    const [timeExpandedMap, setTimeExpandedMap] = useState<Record<string, boolean>>({})

    // 获取数据集列表
    const { data: allDatasets = [], isLoading: datasetsLoading } = useQuery({
        queryKey: ['datasets'],
        queryFn: () => getDatasets()
    })

    // Options for the dataset picker; rows without a code cannot be selected.
    const datasetOptions = useMemo<SelectOption[]>(() => allDatasets
        .filter(d => d.dataset_code != null && d.dataset_code !== '')
        .map(d => ({ value: d.dataset_code, label: t(d.dataset_code) })), [allDatasets, t])

    // Local search also matches the dataset name, code and description
    const filterDataset = (keyword: string, option: SelectOption) => {
        const searchLower = keyword.toLowerCase()
        const d = allDatasets.find(item => item.dataset_code === option.value)
        return option.label.toLowerCase().includes(searchLower) || (!!d && (
            d.dataset_name.toLowerCase().includes(searchLower) ||
            d.dataset_code.toLowerCase().includes(searchLower) ||
            (!!d.description && d.description.toLowerCase().includes(searchLower))
        ))
    }
    // 获取选中的数据集详情
    const selectedDataset = useMemo(() => {
        return allDatasets.find(d => d.dataset_code === selectedDatasetCode)
    }, [allDatasets, selectedDatasetCode])

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
            displayName: d.name,
            fieldType: d.field_type,
            role: "dimension" as const
        }))

        const metrics = selectedDataset.schema_config.metrics.map(m => ({
            fieldCode: m.field,
            fieldId: m.field,
            displayName: m.name,
            fieldType: m.field_type,
            isVirtual: m.is_virtual,
            isDivide: m.formula,
            role: "metric" as const
        }))

        return [...dimensions, ...metrics]
    }, [selectedDataset])

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
                <Select
                    {...selectLabels}
                    className="w-full"
                    options={datasetOptions}
                    value={selectedDatasetCode || null}
                    onChange={(v) => { if (v != null) onDatasetChange?.(String(v)) }}
                    placeholder={t("datasetSelector.selectDataset")}
                    aria-label={t("datasetSelector.dataset")}
                    showSearch
                    filterOption={filterDataset}
                    loading={datasetsLoading}
                    loadingText={t("datasetSelector.loading")}
                    emptyText={t("datasetSelector.noDatasetsFound")}
                    noMatchText={t("datasetSelector.noDatasetsFound")}
                />
            </div>

            {/* 字段展示区域 */}
            {selectedDataset && (
                <div className="flex-1 flex flex-col min-h-0">
                    {!isMetricCard && (
                        <div className="flex-1 flex flex-col min-h-0 border-b">
                            <Button type="button" variant="text" className="w-full px-4 py-3 flex items-center justify-between hover:bg-accent/50 transition-colors shrink-0" onClick={() => setDimensionsExpanded(!dimensionsExpanded)} color="default">
                                <span className="text-sm font-medium">{t("datasetSelector.dimensions")}</span>
                                {dimensionsExpanded ? (
                                    <Outlined.Down className="h-4 w-4" />
                                ) : (
                                    <Outlined.Up className="h-4 w-4" />
                                )}
                            </Button>

                            {dimensionsExpanded && (
                                <div className="flex-1 overflow-y-auto px-4 pb-2 space-y-0 min-h-0">
                                    {selectedDataset.schema_config.dimensions.map((dimension) => {
                                        if (dimension.time_granularitys && dimension.time_granularitys.length > 0) {
                                            return dimension.time_granularitys.map((g) => {
                                                const displayName = t(`${dimension.field}.${g}`)
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
                                            displayName: t(dimension.field),
                                            fieldType: dimension.type === "integer" ? "number" : "string",
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
                                                <span className="text-sm flex-1">{t(dimension.field)}</span>
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    )}

                    {/* 指标区域 - 占据下半部分 */}
                    <div className="flex-1 flex flex-col min-h-0">
                        <Button type="button" variant="text" className="w-full px-4 py-3 flex items-center justify-between hover:bg-accent/50 transition-colors shrink-0" onClick={() => setMetricsExpanded(!metricsExpanded)} color="default">
                            <span className="text-sm font-medium">{t("datasetSelector.metrics")}</span>
                            {metricsExpanded ? (
                                <Outlined.Down className="h-4 w-4" />
                            ) : (
                                <Outlined.Up className="h-4 w-4" />
                            )}
                        </Button>

                        {metricsExpanded && (
                            <div className="flex-1 overflow-y-auto px-4 pb-3 space-y-2 min-h-0">
                                {selectedDataset.schema_config.metrics.map((metric, index) => {
                                    const isVirtual = isVirtualMetric(metric)
                                    const field: DatasetField = {
                                        fieldCode: metric.field,
                                        displayName: t(metric.field),
                                        fieldType: "number",
                                        role: "metric" as const,
                                        isVirtual: metric.is_virtual,
                                        isDivide: metric.formula,
                                    }
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
                                                {t(metric.field)}
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