"use client"

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { copyComponentTo, getDashboards } from "@/controllers/API/dashboard"
import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { useEffect, useMemo, useRef, useState } from "react"
import ReactGridLayout, { Layout, verticalCompactor } from "react-grid-layout"
import "react-grid-layout/css/styles.css"
import { useMutation, useQuery, useQueryClient } from "react-query"
import "react-resizable/css/styles.css"
import { DashboardsQueryKey } from "../../hook"
import { Dashboard } from "../../types/dataConfig"
import { ComponentConfigDrawer } from "./ComponentConfigDrawer"
import "./index.css"
import { ComponentWrapper } from "./ComponentWrapper"

interface EditorCanvasProps {
    isPreviewMode?: boolean
    dashboard: Dashboard | null
}

export function EditorCanvas({ isPreviewMode, dashboard }: EditorCanvasProps) {
    const { width, containerRef, mounted } = useContainerWidth()
    const {
        currentDashboard,
        setCurrentDashboard,
        layouts,
        setLayouts,
        updateComponent: updateComponentInStore,
        duplicateComponent: duplicateComponentInStore,
        deleteComponent: deleteComponentInStore,
        initializeAutoRefresh,
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

    // When the page loads, it automatically refreshes according to the query component configuration 
    useEffect(() => {
        if (currentDashboard && currentDashboard.components.length > 0) {
            // Delay execution to ensure all components are mounted
            const timer = setTimeout(() => {
                initializeAutoRefresh()
            }, 300)
            return () => clearTimeout(timer)
        }
    }, [currentDashboard?.id, initializeAutoRefresh])

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
                clearComponentEditorStore(true)
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

    return (
        <>
        <div className="flex h-full">
            <div
                id="edit-charts-panne"
                ref={containerRef}
                className="flex-1 p-2 overflow-auto"
                style={{
                    backgroundColor: currentDashboard.style_config.theme === 'dark' ? '#1a1a1a' : '#f5f5f5',
                }}
                onClick={handleCanvasClick}
            >
                <div className="mx-auto relative" style={{
                    ...gridBackgroundStyle,
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
                                        isDark={currentDashboard.style_config.theme === 'dark'}
                                        isPreviewMode={isPreviewMode}
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
            </div>
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