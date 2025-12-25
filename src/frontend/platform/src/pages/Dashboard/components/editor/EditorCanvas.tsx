"use client"

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { copyComponentTo, Dashboard, DashboardComponent, getDashboards } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { Copy, Edit3, MoreHorizontal, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import ReactGridLayout, { Layout, verticalCompactor } from "react-grid-layout"
import "react-grid-layout/css/styles.css"
import { useMutation, useQuery, useQueryClient } from "react-query"
import "react-resizable/css/styles.css"
import { DashboardsQueryKey } from "../../hook"
import ChartWidget from "../ChartWidget"
import { ComponentConfigDrawer } from "./ComponentConfigDrawer"
import "./index.css"

interface EditorCanvasProps {
    isPreviewMode?: boolean
    dashboard: Dashboard | null
}

// 组件包装器，用于处理选中状态
interface ComponentWrapperProps {
    component: DashboardComponent
    isSelected: boolean
    isPreviewMode: boolean
    dashboards: Dashboard[],
    onClick: () => void
    onRename: (componentId: string, newTitle: string) => void
    onDuplicate: (componentId: string) => void
    onCopyTo: (componentId: string, targetDashboardId: string) => void
    onDelete: (componentId: string) => void
}

function ComponentWrapper({ dashboards, component, isSelected, isPreviewMode, onClick, onRename, onDuplicate, onCopyTo, onDelete }: ComponentWrapperProps) {
    const [isHovered, setIsHovered] = useState(false)
    const [isEditing, setIsEditing] = useState(false)
    const [title, setTitle] = useState(component.title)
    const inputRef = useRef<HTMLInputElement>(null)
    const { toast } = useToast()

    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [isEditing])

    const handleClick = (e: React.MouseEvent) => {
        e.stopPropagation()
        onClick()
    }

    const handleRenameBlur = () => {
        setIsEditing(false)
        const trimmedTitle = title.trim()

        if (!trimmedTitle) {
            setTitle(component.title)
            toast({
                description: "名称不能为空",
                variant: "error",
            })
            return
        }

        if (trimmedTitle.length < 1 || trimmedTitle.length > 200) {
            setTitle(component.title)
            toast({
                description: "字数范围 1-200 字",
                variant: "error",
            })
            return
        }

        if (trimmedTitle !== component.title) {
            onRename(component.id, trimmedTitle)
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter") {
            inputRef.current?.blur()
        }
        if (e.key === "Escape") {
            setTitle(component.title)
            setIsEditing(false)
        }
    }

    return (
        <div
            className={`group relative w-full h-full bg-background rounded-lg overflow-visible transition-all ${!isPreviewMode && isSelected ? 'ring-2 ring-primary ring-offset-2' : 'border border-border'
                }`}
            onClick={handleClick}
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            style={{ cursor: isPreviewMode ? 'default' : 'pointer' }}
        >
            {/* More button - top right corner */}
            {!isPreviewMode && (isSelected || isHovered) && (
                <div className="absolute top-2 right-2 z-10">
                    <DropdownMenu onOpenChange={() => onClick()}>
                        <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 bg-background/80 backdrop-blur-sm border border-border shadow-sm hover:bg-accent"
                            >
                                <MoreHorizontal className="h-4 w-4" />
                            </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                            <DropdownMenuItem onClick={(e) => {
                                e.stopPropagation()
                                setIsEditing(true)
                            }}>
                                <Edit3 className="h-4 w-4 mr-2" />
                                重命名
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={(e) => {
                                e.stopPropagation()
                                onDuplicate(component.id)
                            }}>
                                <Copy className="h-4 w-4 mr-2" />
                                复制
                            </DropdownMenuItem>
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger onClick={(e) => e.stopPropagation()}>
                                    <Copy className="h-4 w-4 mr-2" />
                                    复制到
                                </DropdownMenuSubTrigger>
                                <DropdownMenuSubContent onClick={(e) => e.stopPropagation()}>
                                    {dashboards.length === 0 ? (
                                        <div className="px-2 py-1.5 text-sm text-muted-foreground">暂无其他看板</div>
                                    ) : (
                                        dashboards
                                            .filter(d => d.id !== component.dashboard_id)
                                            .map(dashboard => (
                                                <DropdownMenuItem
                                                    key={dashboard.id}
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        onCopyTo(component.id, dashboard.id)
                                                    }}
                                                >
                                                    {dashboard.title}
                                                </DropdownMenuItem>
                                            ))
                                    )}
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    onDelete(component.id)
                                }}
                            >
                                <Trash2 className="h-4 w-4 mr-2" />
                                删除
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            )}

            <div className="w-full h-full p-2">
                {/* Component title with rename ability */}
                <div className="mb-2">
                    {isEditing ? (
                        <Input
                            ref={inputRef}
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            onBlur={handleRenameBlur}
                            onKeyDown={handleKeyDown}
                            className="h-7 px-2 text-sm font-medium"
                            onClick={(e) => e.stopPropagation()}
                        />
                    ) : (
                        <h3 className="text-sm font-medium truncate">{component.title}</h3>
                    )}
                </div>

                {/* Component content */}
                {component.type === 'chart' ? (
                    <div className="h-[calc(100%-2.5rem)] overflow-hidden">
                        <ChartWidget type="bar" />
                    </div>
                ) : component.type === 'metric' ? (
                    <div className="h-[calc(100%-2.5rem)] overflow-hidden flex items-center justify-center">
                        <div className="text-center">
                            <div className="text-4xl font-bold text-primary">1,234</div>
                            <div className="text-sm text-muted-foreground mt-2">{component.title}</div>
                        </div>
                    </div>
                ) : (
                    <div className="h-[calc(100%-2.5rem)] overflow-hidden flex items-center justify-center">
                        <div className="text-center">
                            <div className="text-muted-foreground">{component.type} 组件</div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export function EditorCanvas({ isPreviewMode = false, dashboard }: EditorCanvasProps) {
    const { width, containerRef, mounted } = useContainerWidth()
    const {
        currentDashboard,
        setCurrentDashboard,
        layouts,
        setLayouts,
        selectedComponentId,
        setSelectedComponentId,
        updateComponent: updateComponentInStore,
        duplicateComponent: duplicateComponentInStore,
        deleteComponent: deleteComponentInStore,
    } = useEditorDashboardStore()
    console.log('currentDashboard :>> ', currentDashboard);

    const { toast } = useToast()
    const queryClient = useQueryClient()
    // Query to get all dashboards for "Copy to" menu
    const { data: dashboards = [] } = useQuery({
        queryKey: [DashboardsQueryKey],
        queryFn: getDashboards,
        // enabled: isHovered // Only fetch when hovered
    })

    // Mutation for copying component to another dashboard
    const copyToMutation = useMutation({
        mutationFn: ({ componentId, targetId }: { componentId: string; targetId: string }) =>
            copyComponentTo(
                dashboards.find(el => el.id === targetId),
                currentDashboard.components.find(el => el.id === componentId),
                currentDashboard.layout_config.layouts.find(el => el.i === componentId)
            ),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            toast({
                description: "已复制到目标看板",
                variant: "success",
            })
        },
        onError: () => {
            toast({
                description: "复制失败",
                variant: "error",
            })
        },
    })

    // 当dashboard变化时，更新store
    useEffect(() => {
        if (dashboard) {
            setCurrentDashboard(dashboard)
        }
    }, [dashboard, setCurrentDashboard])

    // 处理布局变化
    const handleLayoutChange = (newLayout: Layout[]) => {
        console.log('newLayout :>> ', newLayout);
        if (isPreviewMode) return // 预览模式下不更新布局

        const updatedLayouts = newLayout.map(item => ({
            i: item.i,
            x: item.x,
            y: item.y,
            w: item.w,
            h: item.h,
            minW: item.minW,
            minH: item.minH,
            maxW: item.maxW,
            maxH: item.maxH,
            static: item.static
        }))
        setLayouts(updatedLayouts)
    }

    // 处理组件点击
    const handleComponentClick = (componentId: string) => {
        if (isPreviewMode) return // 预览模式下不选中
        setSelectedComponentId(componentId)
    }

    // 处理画布点击（取消选中）
    const handleCanvasClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget || (e.target as HTMLElement).id === 'edit-charts-panne') {
            setSelectedComponentId(null)
        }
    }

    // Handle component rename
    const handleRename = (componentId: string, newTitle: string) => {
        updateComponentInStore(componentId, { title: newTitle })
    }

    // Handle component duplicate
    const handleDuplicate = (componentId: string) => {
        duplicateComponentInStore(componentId)
    }

    // Handle copy to another dashboard
    const handleCopyTo = (componentId: string, targetDashboardId: string) => {
        copyToMutation.mutate({ componentId, targetId: targetDashboardId })
    }

    // Handle component delete
    const handleDelete = (componentId: string) => {
        const component = currentDashboard?.components.find(c => c.id === componentId)
        if (!component) return

        bsConfirm({
            desc: `确认删除组件"${component.title}"?`,
            okTxt: "删除",
            onOk(next) {
                deleteComponentInStore(componentId)
                next()
            },
        })
    }

    // 如果没有dashboard，显示空状态
    if (!currentDashboard) {
        return (
            <div id="edit-charts-panne" className="flex-1 p-2 bg-muted/30 overflow-auto">
                <div className="max-w-7xl mx-auto">
                    <div className="bg-background rounded-lg border-2 border-dashed p-12 text-center">
                        <p className="text-muted-foreground">加载中...</p>
                    </div>
                </div>
            </div>
        )
    }

    // 如果没有组件，显示空状态
    if (!currentDashboard.components || currentDashboard.components.length === 0) {
        return (
            <div id="edit-charts-panne" className="flex-1 p-2 bg-muted/30 overflow-auto" onClick={handleCanvasClick}>
                <div className="max-w-7xl mx-auto">
                    <div className="bg-background rounded-lg border-2 border-dashed p-12 text-center">
                        <p className="text-muted-foreground">画布区域</p>
                        <p className="text-sm text-muted-foreground mt-2">点击"添加组件"开始设计你的看板</p>
                    </div>
                </div>
            </div>
        )
    }

    // 应用主题
    const currentTheme = currentDashboard.style_config.themes[currentDashboard.style_config.theme]

    // 获取选中的组件
    const selectedComponent = selectedComponentId
        ? currentDashboard.components.find(c => c.id === selectedComponentId)
        : null

    return (
        <>
            <div
                id="edit-charts-panne"
                ref={containerRef}
                className="flex-1 p-2 overflow-auto"
                style={{
                    backgroundColor: currentTheme.backgroundColor,
                }}
                onClick={handleCanvasClick}
            >
                <div className="mx-auto">
                    {mounted && (
                        <ReactGridLayout
                            className="layout"
                            layout={layouts}
                            width={width}
                            gridConfig={{
                                cols: 12,
                                rowHeight: 60
                            }}
                            dragConfig={{ enabled: !isPreviewMode }}
                            resizeConfig={{ enabled: !isPreviewMode }}
                            onLayoutChange={handleLayoutChange}
                            draggableHandle=".drag-handle"
                            margin={[16, 16]}
                            containerPadding={[0, 0]}
                            compactor={verticalCompactor}
                        >
                            {currentDashboard.components.map((component) => (
                                <div key={component.id} className="drag-handle">
                                    <ComponentWrapper
                                        dashboards={dashboards}
                                        component={component}
                                        isSelected={selectedComponentId === component.id}
                                        isPreviewMode={isPreviewMode}
                                        onClick={() => handleComponentClick(component.id)}
                                        onRename={handleRename}
                                        onDuplicate={handleDuplicate}
                                        onCopyTo={handleCopyTo}
                                        onDelete={handleDelete}
                                    />
                                </div>
                            ))}
                        </ReactGridLayout>
                    )}
                </div>
            </div>
            {/* 配置抽屉 */}
            <ComponentConfigDrawer
                open={!!selectedComponentId && !isPreviewMode}
                onOpenChange={(open) => {
                    if (!open) {
                        setSelectedComponentId(null)
                    }
                }}
                component={selectedComponent || null}
                onComponentUpdate={updateComponentInStore}
            />
        </>
    )
}



const useContainerWidth = () => {
    const [width, setWidth] = useState(0);
    const containerRef = useRef(null);
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
        if (!window.ResizeObserver) alert('您的浏览器不支持ResizeObserver，请使用最新版本的Chrome浏览器。');

        const resizeObserver = new ResizeObserver((entries) => {
            for (let entry of entries) {
                if (entry.contentRect) {
                    setWidth(entry.contentRect.width);
                }
            }
        });

        if (containerRef.current) {
            resizeObserver.observe(containerRef.current);
        }

        return () => {
            if (containerRef.current) {
                resizeObserver.unobserve(containerRef.current);
            }
            resizeObserver.disconnect();
        };
    }, [containerRef.current]);

    return { width, containerRef, mounted };
};