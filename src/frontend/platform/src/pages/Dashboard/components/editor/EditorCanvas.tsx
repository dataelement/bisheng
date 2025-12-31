"use client"

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { copyComponentTo, getDashboards } from "@/controllers/API/dashboard"
import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { Copy, Edit3, MoreHorizontal, Trash2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import ReactGridLayout, { Layout, verticalCompactor } from "react-grid-layout"
import "react-grid-layout/css/styles.css"
import { useMutation, useQuery, useQueryClient } from "react-query"
import "react-resizable/css/styles.css"
import { DashboardsQueryKey } from "../../hook"
import { Dashboard, DashboardComponent } from "../../types/dataConfig"
import { ChartContainer } from "../charts/ChartContainer"
import { QueryFilter } from "../charts/QueryFilter"
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
    queryTrigger: number,
    onClick: () => void
    onRename: (componentId: string, newTitle: string) => void
    onDuplicate: (componentId: string) => void
    onCopyTo: (componentId: string, targetDashboardId: string) => void
    onDelete: (componentId: string) => void
}

function ComponentWrapper({
    dashboards, queryTrigger, component, isPreviewMode,
    onRename, onDuplicate, onCopyTo, onDelete
}: ComponentWrapperProps) {
    const [isHovered, setIsHovered] = useState(false)
    const [isEditing, setIsEditing] = useState(false)
    const [title, setTitle] = useState(component.title)
    const inputRef = useRef<HTMLInputElement>(null)
    const { toast } = useToast()
    const { copyFromDashboard, editingComponent, updateEditingComponent } = useComponentEditorStore();
    const isSelected = editingComponent?.id === component.id

    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [isEditing])

    const handleClick = (e: React.MouseEvent) => {
        e.stopPropagation()
        if (isPreviewMode) return
        if (editingComponent?.id === component.id) return
        copyFromDashboard(component.id)
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
                    <DropdownMenu>
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
                            {component.type === 'query' ? (
                                // Query component: only duplicate and delete
                                <>
                                    <DropdownMenuItem onClick={(e) => {
                                        e.stopPropagation()
                                        onDuplicate(component.id)
                                    }}>
                                        <Copy className="h-4 w-4 mr-2" />
                                        复制
                                    </DropdownMenuItem>
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
                                </>
                            ) : (
                                // Other components: full menu
                                <>
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
                                </>
                            )}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            )}

            <div className="w-full h-full p-2">
                {/* Component title with rename ability - hidden for query type */}
                {component.type !== 'query' && (
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
                )}

                {/* Component content */}
                <div className={component.type === 'query' ? 'h-full overflow-hidden' : 'h-[calc(100%-2.5rem)] overflow-hidden'}>
                    {component.type === 'query' ? (
                        <QueryFilter isPreviewMode={isPreviewMode} />
                    ) : (
                        <ChartContainer component={component} queryTrigger={queryTrigger} />
                    )}
                </div>
            </div>
        </div>
    )
}

export function EditorCanvas({ isPreviewMode, dashboard }: EditorCanvasProps) {
    const { width, containerRef, mounted } = useContainerWidth()
    const {
        currentDashboard,
        setCurrentDashboard,
        layouts,
        setLayouts,
        queryTrigger,
        updateComponent: updateComponentInStore,
        duplicateComponent: duplicateComponentInStore,
        deleteComponent: deleteComponentInStore,
    } = useEditorDashboardStore()
    const { clear: clearComponentEditorStore } = useComponentEditorStore();
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

    // 处理画布点击（取消选中）
    const handleCanvasClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget || (e.target as HTMLElement).id === 'edit-charts-panne') {
            clearComponentEditorStore()
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

    const gridBackgroundStyle = useMemo(() => {
        if (isPreviewMode || !width || !mounted) return {};

        const cols = 24;
        const rowHeight = 30;
        const [marginX, marginY] = [16, 12];
        const [padX, padY] = [8, 10];

        const availableWidth = width - (padX * 2);
        const totalMarginWidth = (cols - 1) * marginX;
        const cellWidth = (availableWidth - totalMarginWidth) / cols;

        const patternWidth = cellWidth + marginX;
        const patternHeight = rowHeight + marginY;

        const strokeColor = "rgba(0, 0, 0, 0.08)"; // 虚线颜色
        const dashArray = "4, 2"; // 虚线步长
        const borderRadius = 4; // 圆角

        const svgString = `
            <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <pattern id="grid" x="${padX}" y="${padY}" width="${patternWidth}" height="${patternHeight}" patternUnits="userSpaceOnUse">
                        <rect 
                            x="0" y="0" 
                            width="${cellWidth}" height="${rowHeight}" 
                            fill="transparent" 
                            stroke="${strokeColor}"
                            stroke-width="1"
                            stroke-dasharray="${dashArray}"
                            rx="${borderRadius}" ry="${borderRadius}"
                        />
                    </pattern>
                </defs>
                <rect width="100%" height="100%" fill="url(#grid)" />
            </svg>
        `;

        return {
            backgroundImage: `url("data:image/svg+xml,${encodeURIComponent(svgString)}")`,
            backgroundRepeat: 'repeat',
            backgroundAttachment: 'local',
            backgroundPosition: `${0}px ${0}px`
        };
    }, [width, isPreviewMode, mounted]);

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

    return (
        <>
            <div
                id="edit-charts-panne"
                ref={containerRef}
                className="flex-1 p-2 overflow-auto"
                style={{
                    backgroundColor: currentTheme.backgroundColor
                }}
                onClick={handleCanvasClick}
            >
                <div className="mx-auto relative" style={{
                    ...gridBackgroundStyle, // 应用动态生成的网格背景
                }}>
                    {mounted && (
                        <ReactGridLayout
                            className="layout"
                            layout={layouts}
                            width={width}
                            gridConfig={{
                                cols: 24,
                                rowHeight: 32
                            }}
                            dragConfig={{ enabled: !isPreviewMode }}
                            resizeConfig={
                                {
                                    enabled: !isPreviewMode,
                                    handles: ["sw", "nw", "se", "ne"]
                                }}
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
                                        isPreviewMode={isPreviewMode}
                                        queryTrigger={queryTrigger}
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
            <ComponentConfigDrawer />
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