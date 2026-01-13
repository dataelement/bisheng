"use client"

import { LoadingIcon } from "@/components/bs-icons/loading"
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
import { Dashboard, DashboardComponent } from "../../types/dataConfig"
import { ComponentConfigDrawer } from "../config/ComponentConfigDrawer"
import { ComponentWrapper } from "./ComponentWrapper"
import Home from "./Home"
import "./index.css"
import { cn } from "@/utils"
import { useTranslation } from "react-i18next"

interface EditorCanvasProps {
    isPreviewMode?: boolean
    isLoading: boolean
    dashboard: Dashboard | null
}

export function EditorCanvas({ isLoading, isPreviewMode, dashboard }: EditorCanvasProps) {
    const { width, containerRef, mounted } = useContainerWidth()
    const {
        currentDashboard,
        setCurrentDashboard,
        setCurrentDashboardId,
        layouts,
        setLayouts,
        duplicateComponent: duplicateComponentInStore,
        deleteComponent: deleteComponentInStore,
        initializeAutoRefresh,
    } = useEditorDashboardStore()

    const { clear: clearComponentEditorStore } = useComponentEditorStore();
    const { t } = useTranslation("dashboard")

    const { toast } = useToast()
    const queryClient = useQueryClient()
    // Query to get all dashboards for "Copy to" menu
    const { data: dashboards = [] } = useQuery({
        queryKey: [DashboardsQueryKey],
        queryFn: getDashboards,
        // enabled: isHovered // Only fetch when hovered
    })

    const theme = currentDashboard?.style_config?.theme

    // Mutation for copying component to another dashboard
    const copyToMutation = useMutation({
        mutationFn: ({ component, targetId }: { component: DashboardComponent; targetId: string, }) =>
            copyComponentTo(component, targetId, layouts.find(e => e.i === component.id)),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            toast({
                description: t('copyToTargetSuccess'),
                variant: "success",
            })
        },
        onError: () => {
            toast({
                description: t('copyFailed'),
                variant: "error",
            })
        },
    })

    // 当dashboard变化时，更新store
    useEffect(() => {
        if (dashboard) {
            setCurrentDashboard(dashboard)
            setCurrentDashboardId(dashboard.id)
        }
    }, [dashboard, setCurrentDashboard])

    // When the page loads, it automatically refreshes according to the query component configuration 
    useEffect(() => {
        console.log('currentDashboard :>> ', currentDashboard);
        if (currentDashboard && currentDashboard.components.length > 0) {
            // Delay execution to ensure all components are mounted
            const timer = setTimeout(() => {
                initializeAutoRefresh()
            }, 300)
            return () => clearTimeout(timer)
        }
    }, [currentDashboard?.id, initializeAutoRefresh])

    // 处理布局变化
    const isInitialMount = useRef(true);
    const handleLayoutChange = (newLayout: Layout[]) => {
        if (isPreviewMode) return // 预览模式下不更新布局
        if (isInitialMount.current) {
            isInitialMount.current = false;
            return;
        }
        console.log('newLayout :>> ', newLayout);

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
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as HTMLElement;
            const isInsideContainer = containerRef.current?.contains(target);
            const isDragHandle = target.closest('.drag-handle');
            if (isInsideContainer && !isDragHandle) {
                clearComponentEditorStore();
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, []);

    // Handle component duplicate
    const handleDuplicate = (component: DashboardComponent) => {
        duplicateComponentInStore(component)
    }

    // Handle copy to another dashboard
    const handleCopyTo = (component: DashboardComponent, targetDashboardId: string) => {
        copyToMutation.mutate({ component, targetId: targetDashboardId })
    }

    // Handle component delete
    const handleDelete = (componentId: string) => {
        const component = currentDashboard?.components.find(c => c.id === componentId)
        if (!component) return

        bsConfirm({
            desc: t('confirmDeleteComponent', { name: component.title }),
            okTxt: t('delete'),
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
        const rowHeight = 32;
        const [marginX, marginY] = [8, 8];
        const [padX, padY] = [16, 16];

        const availableWidth = width - (padX * 2);
        const totalMarginWidth = (cols - 1) * marginX;
        const cellWidth = (availableWidth - totalMarginWidth) / cols;

        const patternWidth = cellWidth + marginX;
        const patternHeight = rowHeight + marginY;

        const strokeColor = theme === 'dark' ? "#666" : "rgba(0, 0, 0, 0.08)"; // 虚线颜色
        const dashArray = "4, 3"; // 虚线步长
        const borderRadius = 10; // 圆角

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
               <rect 
                    x="${padX}" 
                    y="${padY}" 
                    width="calc(100% - ${padX * 2}px)" 
                    height="calc(100% - ${padY * 2}px)" 
                    fill="url(#grid)" 
                />
            </svg>
        `;

        return {
            backgroundImage: `url("data:image/svg+xml,${encodeURIComponent(svgString)}")`,
            backgroundRepeat: 'repeat',
            backgroundAttachment: 'local',
            backgroundPosition: `${0}px ${0}px`,
            // height: '100%'
        };
    }, [width, isPreviewMode, mounted, currentDashboard?.style_config.theme]);


    // loading
    if (isLoading || !currentDashboard) {
        return <div className="w-full h-full flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>
    }

    // show home
    if (!currentDashboard.components || currentDashboard.components.length === 0) {
        if (isPreviewMode) {
            return
        }
        return <Home />
    }

    return (
        <>
            <div className="flex h-full">
                <div
                    id="edit-charts-panne"
                    ref={containerRef}
                    className={cn("flex-1 overflow-auto", theme)}
                    style={{
                        backgroundColor: theme === 'dark' ? '#1a1a1a' : '#f5f5f5',
                    }}
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
                                    rowHeight: 32,
                                    margin: [8, 8],
                                    containerPadding: [16, 16]
                                }}
                                dragConfig={{
                                    enabled: !isPreviewMode,
                                    // handle: ".drag-handle",
                                    cancel: ".no-drag,input"
                                }}
                                resizeConfig={
                                    {
                                        enabled: !isPreviewMode,
                                        handles: ["sw", "nw", "se", "ne"]
                                    }}
                                onLayoutChange={handleLayoutChange}
                                compactor={verticalCompactor}
                            >
                                {currentDashboard.components.map((component) => (
                                    <div key={component.id} className="drag-handle">
                                        <ComponentWrapper
                                            dashboards={dashboards}
                                            component={component}
                                            isDark={theme === 'dark'}
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
                {/* drawer */}
                {!isPreviewMode && <ComponentConfigDrawer />}
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
        if (!window.ResizeObserver) alert('Your browser does not support ResizeObserver. Please use the latest version of Chrome browser.');

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