"use client"

import { Button } from "@/components/bs-ui/button"
import { Sheet, SheetContent } from "@/components/bs-ui/sheet"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { useState } from "react"
import { DashboardComponent } from "../../types/dataConfig"
import { DatasetSelector } from "./DatasetSelector"
import "./index.css"

interface ComponentConfigDrawerProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    component: DashboardComponent | null
    onComponentUpdate?: (componentId: string, data: Partial<DashboardComponent>) => void
}

export function ComponentConfigDrawer({
    open,
    onOpenChange,
    component,
    onComponentUpdate
}: ComponentConfigDrawerProps) {
    // 基础配置区域和数据选择区域的展开状态
    const [basicConfigCollapsed, setBasicConfigCollapsed] = useState(false)
    const [dataConfigCollapsed, setDataConfigCollapsed] = useState(false)

    // 处理数据集变更
    const handleDatasetChange = (datasetCode: string) => {
        if (component && onComponentUpdate) {
            onComponentUpdate(component.id, { dataset_code: datasetCode })
        }
    }

    if (!component) return null

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                noOverlay
                noClose
                side="right"
                className="w-[800px] max-w-[90vw] p-0 flex"
            >
                {/* 基础配置区域 */}
                <div
                    className={`border-r transition-all duration-300 flex flex-col bg-background ${basicConfigCollapsed ? 'w-12' : 'w-[400px]'
                        }`}
                >
                    {basicConfigCollapsed ? (
                        /* 收起状态 - 竖向显示 */
                        <div
                            className="flex-1 flex flex-col items-center justify-center cursor-pointer hover:bg-accent/50 transition-colors"
                            onClick={() => setBasicConfigCollapsed(false)}
                        >
                            <div className="writing-mode-vertical text-sm font-medium whitespace-nowrap py-4">
                                基础配置
                            </div>
                            <ChevronRight className="h-4 w-4 mt-2" />
                        </div>
                    ) : (
                        /* 展开状态 */
                        <div className="flex-1 overflow-hidden flex flex-col">
                            {/* 标题 */}
                            <div className="px-4 py-4 border-b flex items-center justify-between">
                                <h3 className="text-lg font-semibold">基础配置</h3>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6"
                                    onClick={() => setBasicConfigCollapsed(true)}
                                >
                                    <ChevronLeft className="h-4 w-4" />
                                </Button>
                            </div>

                            {/* 配置内容 */}
                            <div className="flex-1 overflow-y-auto p-4">
                                <div className="text-sm text-muted-foreground">
                                    基础配置区域（待实现）
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* 数据选择区域 */}
                <div
                    className={`transition-all duration-300 flex flex-col bg-background ${dataConfigCollapsed ? 'w-12' : 'flex-1 min-w-[320px]'
                        }`}
                >
                    {dataConfigCollapsed ? (
                        /* 收起状态 - 竖向显示 */
                        <div
                            className="flex-1 flex flex-col items-center justify-center cursor-pointer hover:bg-accent/50 transition-colors"
                            onClick={() => setDataConfigCollapsed(false)}
                        >
                            <div className="writing-mode-vertical text-sm font-medium whitespace-nowrap py-4">
                                数据集配置
                            </div>
                            <ChevronLeft className="h-4 w-4 mt-2" />
                        </div>
                    ) : (
                        /* 展开状态 */
                        <div className="flex-1 overflow-hidden flex flex-col">
                            {/* 标题 */}
                            <div className="px-4 py-4 border-b flex items-center justify-between">
                                <h3 className="text-lg font-semibold">数据集配置</h3>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6"
                                    onClick={() => setDataConfigCollapsed(true)}
                                >
                                    <ChevronRight className="h-4 w-4" />
                                </Button>
                            </div>

                            {/* 数据集选择器 */}
                            <div className="flex-1 overflow-hidden">
                                <DatasetSelector
                                    selectedDatasetCode={component.dataset_code}
                                    onDatasetChange={handleDatasetChange}
                                />
                            </div>
                        </div>
                    )}
                </div>
            </SheetContent>
        </Sheet>
    )
}
