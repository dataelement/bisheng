// @ts-strict-ignore
import { Button, Dropdown, DropdownItem, DropdownSeparator, DropdownSub, Input, notification } from '@bisheng/ui';



import { useComponentEditorStore } from "@/store/dashboardStore";
import { cn } from "@/utils";
import { Tooltip as Tip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { GripHorizontalIcon } from "lucide-react";
import { memo,useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { ChartType,Dashboard,DashboardComponent } from "../../types/dataConfig";
import { ChartContainer } from "../charts/ChartContainer";
import { QueryFilter } from "../charts/QueryFilter";
import "./index.css";

interface ComponentWrapperProps {
    component: DashboardComponent
    isPreviewMode: boolean
    dashboards: Dashboard[]
    /** When it is true, the dark selector can take effect, resolving the conflict between the system and canvas themes  */
    isDark: boolean
    onDuplicate: (component: DashboardComponent) => void
    onCopyTo: (component: DashboardComponent, targetDashboardId: string) => void
    onDelete: (componentId: string) => void
}

// 组件包装器，用于处理选中状态
export const ComponentWrapper = memo(({
    dashboards, component, isPreviewMode, isDark,
    onDuplicate, onCopyTo, onDelete
}: ComponentWrapperProps) => {
    const { t } = useTranslation("dashboard")

    const [isHovered, setIsHovered] = useState(false)
    const [isEditing, setIsEditing] = useState(false)
    const inputRef = useRef<HTMLInputElement>(null)

    const [title, setTitle] = useState('')
    const { hasChange, copyFromDashboard, editingComponent, updateEditingComponent } = useComponentEditorStore();
    const isSelected = editingComponent?.id === component.id
    const componentData = isSelected ? editingComponent : component
    // "Copy to" only offers other dashboards that are still drafts.
    const copyTargets = dashboards.filter(d => d.id !== component.dashboard_id && d.status === 'draft')

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
            notification.open({ type: "error", description: String(t('charLimit200') ?? '') })
            return
        }

        if (trimmedTitle !== component.title) {
            setTitle(trimmedTitle)
            // onRename(component.id, trimmedTitle)
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
            titleBold: false,
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
            id={component.id}
            className={cn(`relative w-full h-full rounded-md overflow-visible transition-all border ${!isPreviewMode && isSelected ? 'component-select border border-primary' : ''
                }`,
                !componentData.style_config.bgColor && isDark && 'dark:bg-gray-900',
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
                // Menu clicks bubble through the portal; keep them off the card's
                // onClick (opening the menu already selects the component).
                <div className="absolute top-2 right-2 z-10" onClick={(e) => e.stopPropagation()}>
                    <Dropdown
                        align="end"
                        onOpenChange={(b) => b && handleClick()}
                        panelClassName={isDark ? 'dark' : undefined}
                        menu={ChartType.Query === component.type ? (
                            // Query component: only duplicate and delete
                            <>
                                <DropdownItem icon={<Outlined.Copy />} onSelect={() => onDuplicate(componentData)}>
                                    {t('duplicate')}
                                </DropdownItem>
                                <DropdownSeparator />
                                <DropdownItem danger icon={<Outlined.Delete />} onSelect={() => onDelete(component.id)}>
                                    {t('delete')}
                                </DropdownItem>
                            </>
                        ) : (
                            // Other components: full menu
                            <>
                                {ChartType.Metric !== component.type && (
                                    <DropdownItem icon={<Outlined.Edit />} onSelect={() => setIsEditing(true)}>
                                        {t('rename')}
                                    </DropdownItem>
                                )}
                                <DropdownItem icon={<Outlined.Copy />} onSelect={() => onDuplicate(componentData)}>
                                    {t('duplicate')}
                                </DropdownItem>
                                <DropdownSub icon={<Outlined.Copy />} label={t('copyTo')}>
                                    {copyTargets.length === 0 ? (
                                        <DropdownItem disabled>{t('noOtherDashboards')}</DropdownItem>
                                    ) : (
                                        copyTargets.map(dashboard => (
                                            <DropdownItem
                                                key={dashboard.id}
                                                onSelect={() => onCopyTo(componentData, dashboard.id)}
                                            >
                                                <Tip content={dashboard.title}>
                                                    <span className="block truncate">{dashboard.title}</span>
                                                </Tip>
                                            </DropdownItem>
                                        ))
                                    )}
                                </DropdownSub>
                                <DropdownSeparator />
                                <DropdownItem danger icon={<Outlined.Delete />} onSelect={() => onDelete(component.id)}>
                                    {t('delete')}
                                </DropdownItem>
                            </>
                        )}
                    >
                        <Button variant="text" size="medium" className="h-6 w-6 bg-background/80 border border-border shadow-sm hover:bg-accent dark:border-gray-500 dark:text-gray-500" color="default" iconOnly>
                            <Outlined.More className="h-4 w-4" />
                        </Button>
                    </Dropdown>
                </div>
            )}

            <div className="w-full h-full p-2">
                {/* Component title with rename ability - hidden for query type */}
                {!['query', 'metric'].includes(componentData.type) && (
                    <div className="group mb-2 relative">
                        {isEditing ? (
                            <Input ref={inputRef} value={title} onChange={(e) => setTitle(e.target.value)} onBlur={handleRenameBlur} onKeyDown={handleKeyDown} onClick={(e) => e.stopPropagation()} className={"max-w-40 h-5 px-2 text-sm font-medium border-primary"} />
                        ) : (
                            <h3
                                className={cn("text-sm font-medium truncate text-foreground",
                                    isDark && "dark:text-gray-400"
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
});

