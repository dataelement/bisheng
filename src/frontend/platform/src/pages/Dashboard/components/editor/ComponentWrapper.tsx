import { Button } from "@/components/bs-ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useComponentEditorStore } from "@/store/dashboardStore"
import { Copy, Edit3, GripHorizontalIcon, MoreHorizontal, MoreVerticalIcon, Trash2 } from "lucide-react"
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
    const [title, setTitle] = useState('')
    const { hasChange, copyFromDashboard, editingComponent, updateEditingComponent } = useComponentEditorStore();
    const isSelected = editingComponent?.id === component.id
    const componentData = isSelected ? editingComponent : component

    useEffect(() => {
        console.log('componentData :>> ', componentData);
        setTitle(componentData.title)
    }, [editingComponent])

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

    const createTitleStyle = (config) => {
        const defaultConfig = {
            titleFontSize: 16,
            titleColor: "",
            titleAlign: "left",
            titleBold: true,
            titleItalic: false,
            titleUnderline: false,
            titleStrikethrough: false,
            ...config  // 用户配置覆盖默认值
        };

        return {
            fontSize: `${defaultConfig.titleFontSize}px`,
            color: defaultConfig.titleColor,
            textAlign: defaultConfig.titleAlign,
            fontWeight: defaultConfig.titleBold ? 'bold' : 'normal',
            fontStyle: defaultConfig.titleItalic ? 'italic' : 'normal',
            textDecoration: [
                defaultConfig.titleUnderline ? 'underline' : '',
                defaultConfig.titleStrikethrough ? 'line-through' : ''
            ].filter(Boolean).join(' ') || 'none',
            // 确保span能够应用text-align（如果需要）
            display: 'inline-block',
            maxWidth: '85%',
            lineHeight: 1,
            // width: '100%'
        };
    };

    return (
        <div
            className={cn(`relative w-full h-full rounded-md overflow-visible transition-all border ${!isPreviewMode && isSelected ? 'component-select border border-primary' : ''
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
                            {ChartType.Query === component.type ? (
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
                                    {
                                        ChartType.Metric !== component.type && <DropdownMenuItem onClick={(e) => {
                                            e.stopPropagation()
                                            setIsEditing(true)
                                        }}>
                                            <Edit3 className="h-4 w-4 mr-2" />
                                            {t('rename')}
                                        </DropdownMenuItem>
                                    }
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
                {!['query', 'metric'].includes(componentData.type) && (
                    <div className="group mb-2 relative">
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
                            <h3
                                className={cn("text-sm font-medium truncate",
                                    "dark:text-gray-400"
                                )}
                                style={{ textAlign: componentData.style_config?.titleAlign }}
                                onDoubleClick={() => setIsEditing(true)}>
                                <span className="no-drag cursor-pointer truncate" style={createTitleStyle(componentData.style_config)}>{title}</span>
                            </h3>
                        )}
                        {!isPreviewMode && <GripHorizontalIcon
                            className={cn(
                                "absolute -top-1 left-1/2 -translate-x-1/2 text-gray-400 transition-opacity",
                                "opacity-0",
                                "group-hover:opacity-100",
                                "group-has-[.no-drag:hover]:opacity-0"
                            )}
                            size={16}
                        />}
                    </div>
                )}

                {/* Component content */}
                <div
                    className={['query', 'metric'].includes(componentData.type) ? '' : ` no-drag cursor-default`}
                    style={{
                        height: ['query', 'metric'].includes(componentData.type) ? '100%' : `calc(100% - ${(componentData.style_config?.titleFontSize || 0) + 10}px)`
                    }}
                >
                    {componentData.type === 'query' ? (
                        <QueryFilter
                            isDark={isDark}
                            component={componentData}
                            isPreviewMode={isPreviewMode}
                            hasChanged={hasChange}
                        />
                    ) : (
                        <ChartContainer isDark={isDark} component={componentData} isPreviewMode={isPreviewMode} />
                    )}
                </div>
            </div>
        </div>
    )
}
