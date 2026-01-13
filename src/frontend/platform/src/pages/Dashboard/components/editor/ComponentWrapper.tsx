import { Button } from "@/components/bs-ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useComponentEditorStore } from "@/store/dashboardStore"
import { Copy, Edit3, MoreHorizontal, MoreVerticalIcon, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { ChartType, Dashboard, DashboardComponent } from "../../types/dataConfig"
import { ChartContainer } from "../charts/ChartContainer"
import { QueryFilter } from "../charts/QueryFilter"
import "./index.css"
import { cn } from "@/utils"
import { useTranslation } from "react-i18next"
import Tip from "@/components/bs-ui/tooltip/tip"

interface ComponentWrapperProps {
    component: DashboardComponent
    isPreviewMode: boolean
    dashboards: Dashboard[]
    isDark: boolean
    onDuplicate: (component: DashboardComponent) => void
    onCopyTo: (component: DashboardComponent, targetDashboardId: string) => void
    onDelete: (componentId: string) => void
    onRename: (componentId: string, newTitle: string) => void
}

// 组件包装器，用于处理选中状态
export function ComponentWrapper({
    dashboards, component, isPreviewMode, isDark,
    onDuplicate, onCopyTo, onDelete, onRename
}: ComponentWrapperProps) {
    const { t } = useTranslation("dashboard")

    const [isHovered, setIsHovered] = useState(false)
    const [isEditing, setIsEditing] = useState(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const { toast } = useToast()
    const [title, setTitle] = useState(component.title)
    const { copyFromDashboard, editingComponent, updateEditingComponent } = useComponentEditorStore();
    const isSelected = editingComponent?.id === component.id
    const componentData = isSelected ? editingComponent : component

    useEffect(() => {
        console.log('componentData :>> ', componentData);
    }, [editingComponent, component])

    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [isEditing])

    const handleClick = (e?: React.MouseEvent) => {
        e?.stopPropagation()
        if (isPreviewMode) return
        if (editingComponent?.id === component.id) return
        copyFromDashboard(component.id)
    }

    const handleRenameBlur = () => {
        setIsEditing(false)
        const trimmedTitle = title.trim()

        if (!trimmedTitle) {
            setTitle(component.title)
            // toast({
            //     description: t('nameRequired'),
            //     variant: "error",
            // })
            return
        }

        if (trimmedTitle.length < 1 || trimmedTitle.length > 200) {
            setTitle(component.title)
            toast({
                description: t('charLimit200'),
                variant: "error",
            })
            return
        }

        if (trimmedTitle !== component.title) {
            setTitle(trimmedTitle)
            onRename(component.id, trimmedTitle)
            updateEditingComponent({ title: trimmedTitle })
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter") {
            inputRef.current?.blur()
        }
        if (e.key === "Escape") {
            // setTitle(component.title)
            setIsEditing(false)
        }
    }

    return (
        <div
            className={cn(`group relative w-full h-full rounded-md overflow-visible transition-all border ${!isPreviewMode && isSelected ? 'component-select border border-primary' : ''
                }`,
                !componentData.style_config.bgColor && 'dark:bg-gray-900',
                !componentData.style_config.bgColor && 'bg-background',
                !isPreviewMode && 'hover:border-primary hover:shadow-md'
            )}
            onClick={handleClick}
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            style={{
                cursor: isPreviewMode ? 'default' : 'grab',
                backgroundColor: componentData.style_config.bgColor,
            }}
        >
            {/* More button - top right corner */}
            {!isPreviewMode && (isSelected || isHovered) && (
                <div className="absolute top-2 right-2 z-10">
                    <DropdownMenu onOpenChange={(b) => b && handleClick()}>
                        <DropdownMenuTrigger asChild>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 bg-background/80 backdrop-blur-sm border border-border shadow-sm hover:bg-accent dark:border-gray-500 dark:text-gray-500"
                            >
                                <MoreVerticalIcon className="h-4 w-4" />
                            </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className={isDark && 'dark border-gray-700'}>
                            {[ChartType.Metric, ChartType.Query].includes(component.type) ? (
                                // Query component: only duplicate and delete
                                <>
                                    <DropdownMenuItem onClick={(e) => {
                                        e.stopPropagation()
                                        onDuplicate(componentData)
                                    }}>
                                        <Copy className="h-4 w-4 mr-2" />
                                        {t('duplicate')}
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        variant="destructive"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            onDelete(component.id)
                                        }}
                                    >
                                        <Trash2 className="h-4 w-4 mr-2" />
                                        {t('delete')}
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
                                        {t('rename')}
                                    </DropdownMenuItem>
                                    <DropdownMenuItem onClick={(e) => {
                                        e.stopPropagation()
                                        onDuplicate(componentData)
                                    }}>
                                        <Copy className="h-4 w-4 mr-2" />
                                        {t('duplicate')}
                                    </DropdownMenuItem>
                                    <DropdownMenuSub>
                                        <DropdownMenuSubTrigger onClick={(e) => e.stopPropagation()}>
                                            <Copy className="h-4 w-4 mr-2" />
                                            {t('copyTo')}
                                        </DropdownMenuSubTrigger>
                                        <DropdownMenuSubContent onClick={(e) => e.stopPropagation()}>
                                            {dashboards.length === 0 ? (
                                                <div className="px-2 py-1.5 text-sm text-muted-foreground">{t('noOtherDashboards')}</div>
                                            ) : (
                                                dashboards
                                                    .filter(d => d.id !== component.dashboard_id && d.status === 'draft' && d.write)
                                                    .map(dashboard => (
                                                        <DropdownMenuItem
                                                            key={dashboard.id}
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                onCopyTo(componentData, dashboard.id)
                                                            }}
                                                        >
                                                            <Tip content={dashboard.title} styleClasses="max-w-60 max-h-60 overflow-auto bg-black no-scrollbar">
                                                                <div className="max-w-60 truncate">{dashboard.title}</div>
                                                            </Tip>
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
                                        {t('delete')}
                                    </DropdownMenuItem>
                                </>
                            )}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            )}

            <div className="w-full h-full p-2">
                {/* Component title with rename ability - hidden for query type */}
                {!['query', 'metric'].includes(component.type) && (
                    <div className="mb-2">
                        {isEditing ? (
                            <Input
                                ref={inputRef}
                                value={title}
                                onChange={(e) => setTitle(e.target.value)}
                                onBlur={handleRenameBlur}
                                onKeyDown={handleKeyDown}
                                className="max-w-40 h-5 px-2 text-sm font-medium border-primary"
                                onClick={(e) => e.stopPropagation()}
                            />
                        ) : (
                            <h3 className={cn("no-drag text-sm font-medium truncate cursor-pointer block",
                                "dark:text-gray-400"
                            )} onDoubleClick={() => setIsEditing(true)}>{title}</h3>
                        )}
                    </div>
                )}

                {/* Component content */}
                <div className={['query', 'metric'].includes(component.type) ? 'h-full overflow-hidden' : 'h-[calc(100%-2.5rem)] overflow-hidden no-drag cursor-default'}>
                    {component.type === 'query' ? (
                        <QueryFilter isDark={isDark} component={componentData} isPreviewMode={isPreviewMode} />
                    ) : (
                        <ChartContainer isDark={isDark} component={componentData} isPreviewMode={isPreviewMode} />
                    )}
                </div>
            </div>
        </div>
    )
}
