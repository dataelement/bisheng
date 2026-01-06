import { Button } from "@/components/bs-ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useComponentEditorStore } from "@/store/dashboardStore"
import { Copy, Edit3, MoreHorizontal, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { ChartType, Dashboard, DashboardComponent } from "../../types/dataConfig"
import { ChartContainer } from "../charts/ChartContainer"
import { QueryFilter } from "../charts/QueryFilter"
import "./index.css"

interface ComponentWrapperProps {
    component: DashboardComponent
    isPreviewMode: boolean
    dashboards: Dashboard[]
    isDark: boolean
    onDuplicate: (componentId: string) => void
    onCopyTo: (componentId: string, targetDashboardId: string) => void
    onDelete: (componentId: string) => void
}

// 组件包装器，用于处理选中状态
export function ComponentWrapper({
    dashboards, component, isPreviewMode, isDark,
    onDuplicate, onCopyTo, onDelete
}: ComponentWrapperProps) {
    const [isHovered, setIsHovered] = useState(false)
    const [isEditing, setIsEditing] = useState(false)
    const [title, setTitle] = useState(component.title)
    const inputRef = useRef<HTMLInputElement>(null)
    const { toast } = useToast()
    const { copyFromDashboard, editingComponent, updateEditingComponent } = useComponentEditorStore();
    const isSelected = editingComponent?.id === component.id
    const componentData = isSelected ? editingComponent : component

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
            updateEditingComponent({ title: trimmedTitle })
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
            {!isPreviewMode && (isSelected || isHovered) && componentData.type !== ChartType.Metric && (
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
                {!['query', 'metric'].includes(component.type) && (
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
                <div className={['query', 'metric'].includes(component.type) ? 'h-full overflow-hidden' : 'h-[calc(100%-2.5rem)] overflow-hidden'}>
                    {component.type === 'query' ? (
                        <QueryFilter isDark={isDark} component={componentData} isPreviewMode={isPreviewMode} />
                    ) : (
                        <ChartContainer isDark={isDark} component={componentData} />
                    )}
                </div>
            </div>
        </div>
    )
}
