"use client"

import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { getDatasets, MetricConfig } from "@/controllers/API/dashboard"
import { Calendar, ChevronDown, ChevronRight, Hash, Search, Type } from "lucide-react"
import { useMemo, useState } from "react"
import { useQuery } from "react-query"

interface DatasetSelectorProps {
    selectedDatasetCode?: string
    onDatasetChange?: (datasetCode: string) => void
}

// 根据字段类型返回对应的图标
const getFieldTypeIcon = (type: 'integer' | 'keyword' | 'date') => {
    switch (type) {
        case 'date':
            return <Calendar className="h-4 w-4" />
        case 'integer':
            return <Hash className="h-4 w-4" />
        case 'keyword':
            return <Type className="h-4 w-4" />
    }
}

// 判断是否为虚拟指标
const isVirtualMetric = (metric: MetricConfig): boolean => {
    // 虚拟指标的判断逻辑，这里简单判断是否有 bucket_path
    return metric.bucket_path !== undefined && metric.bucket_path !== metric.aggregation_name
}

export function DatasetSelector({ selectedDatasetCode, onDatasetChange }: DatasetSelectorProps) {
    const [searchTerm, setSearchTerm] = useState("")
    const [dimensionsExpanded, setDimensionsExpanded] = useState(true)
    const [metricsExpanded, setMetricsExpanded] = useState(true)

    // 获取数据集列表
    const { data: allDatasets = [], isLoading: datasetsLoading } = useQuery({
        queryKey: ['datasets'],
        queryFn: () => getDatasets({ limit: 11 }),
    })

    // 前端搜索过滤
    const filteredDatasets = useMemo(() => {
        if (!searchTerm) return allDatasets
        const searchLower = searchTerm.toLowerCase()
        return allDatasets.filter(d =>
            d.dataset_name.toLowerCase().includes(searchLower) ||
            d.dataset_code.toLowerCase().includes(searchLower) ||
            d.description.toLowerCase().includes(searchLower)
        )
    }, [allDatasets, searchTerm])

    // 获取选中的数据集详情
    const selectedDataset = useMemo(() => {
        return allDatasets.find(d => d.dataset_code === selectedDatasetCode)
    }, [allDatasets, selectedDatasetCode])

    return (
        <div className="flex flex-col h-full">
            {/* 数据集选择 */}
            <div className="p-4 border-b">
                <Label className="text-sm font-medium mb-2 block">数据集</Label>
                <Select value={selectedDatasetCode} onValueChange={onDatasetChange}>
                    <SelectTrigger className="w-full">
                        <SelectValue placeholder="选择数据集" />
                    </SelectTrigger>
                    <SelectContent>
                        {/* 搜索框 */}
                        <div className="px-2 py-1.5">
                            <div className="relative">
                                <Search className="absolute left-2 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                <Input
                                    placeholder="搜索数据集..."
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
                                加载中...
                            </div>
                        ) : filteredDatasets.length === 0 ? (
                            <div className="px-2 py-4 text-sm text-muted-foreground text-center">
                                未找到数据集
                            </div>
                        ) : (
                            filteredDatasets.map((dataset) => (
                                <SelectItem key={dataset.dataset_code} value={dataset.dataset_code}>
                                    {dataset.dataset_name}
                                </SelectItem>
                            ))
                        )}
                    </SelectContent>
                </Select>
            </div>

            {/* 字段展示区域 */}
            {selectedDataset && (
                <div className="flex-1 overflow-y-auto">
                    {/* 维度区域 */}
                    <div className="border-b">
                        <button
                            className="w-full px-4 py-3 flex items-center justify-between hover:bg-accent/50 transition-colors"
                            onClick={() => setDimensionsExpanded(!dimensionsExpanded)}
                        >
                            <span className="text-sm font-medium">维度</span>
                            {dimensionsExpanded ? (
                                <ChevronDown className="h-4 w-4" />
                            ) : (
                                <ChevronRight className="h-4 w-4" />
                            )}
                        </button>
                        {dimensionsExpanded && (
                            <div className="px-4 pb-3 space-y-2">
                                {selectedDataset.schema_config.dimensions.map((dimension, index) => (
                                    <div
                                        key={index}
                                        className="flex items-center gap-2 p-2 rounded hover:bg-accent/30 cursor-pointer transition-colors"
                                        draggable
                                        onDragStart={(e) => {
                                            e.dataTransfer.setData('dimension', JSON.stringify(dimension))
                                        }}
                                    >
                                        <div className="text-blue-500">
                                            {getFieldTypeIcon(dimension.type)}
                                        </div>
                                        <span className="text-sm flex-1">{dimension.name}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* 指标区域 */}
                    <div>
                        <button
                            className="w-full px-4 py-3 flex items-center justify-between hover:bg-accent/50 transition-colors"
                            onClick={() => setMetricsExpanded(!metricsExpanded)}
                        >
                            <span className="text-sm font-medium">指标</span>
                            {metricsExpanded ? (
                                <ChevronDown className="h-4 w-4" />
                            ) : (
                                <ChevronRight className="h-4 w-4" />
                            )}
                        </button>
                        {metricsExpanded && (
                            <div className="px-4 pb-3 space-y-2">
                                {selectedDataset.schema_config.metrics.map((metric, index) => {
                                    const isVirtual = isVirtualMetric(metric)
                                    return (
                                        <div
                                            key={index}
                                            className="flex items-center gap-2 p-2 rounded hover:bg-accent/30 cursor-pointer transition-colors"
                                            draggable
                                            onDragStart={(e) => {
                                                e.dataTransfer.setData('metric', JSON.stringify(metric))
                                            }}
                                        >
                                            <div className="text-green-500">
                                                <Hash className="h-4 w-4" />
                                            </div>
                                            <span className="text-sm flex-1">
                                                {metric.name}
                                                {isVirtual && <span className="text-muted-foreground">*</span>}
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
                        请先选择一个数据集
                    </p>
                </div>
            )}
        </div>
    )
}
