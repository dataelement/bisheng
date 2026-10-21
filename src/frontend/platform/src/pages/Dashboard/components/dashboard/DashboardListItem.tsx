// @ts-strict-ignore
import { Button, Input, notification } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import type React from "react";


import { DropdownMenu,DropdownMenuContent,DropdownMenuItem,DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu";


import { locationContext } from "@/contexts/locationContext";
import { cn } from "@/utils";
import { Tag } from "@bisheng/ui";

import { useContext,useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { useLazyDashboardPermission } from "../../hook";
import { Dashboard } from "../../types/dataConfig";


interface DashboardListItemProps {
    dashboard: Dashboard
    selected: boolean
    onSelect: () => void
    onRename: (id: string, newTitle: string) => void
    onDuplicate: (dashboard: Dashboard) => void
    onDefault: (id: string) => void
    onShare: (id: string) => void
    onDelete: (id: string) => void
    onPermission?: (dashboard: Dashboard) => void
    permissionBadge?: React.ReactNode
}

export function DashboardListItem({
    dashboard,
    selected,
    onSelect,
    onRename,
    onDuplicate,
    onShare,
    onDefault,
    onDelete,
    onPermission,
    permissionBadge,
}: DashboardListItemProps) {
    const { t } = useTranslation("dashboard")

    const [isEditing, setIsEditing] = useState(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const [title, setTitle] = useState('')

    const { appConfig } = useContext(locationContext)

    // Visibility is decided by the server list; edit/delete/manage_permission
    // are resolved lazily the moment the user reaches for them (menu open or a
    // double-click rename), so the list never front-loads a request per row.
    const { actions, privileged, ensureLoaded } = useLazyDashboardPermission(String(dashboard.id))

    useEffect(() => {
        setTitle(dashboard.title)
    }, [dashboard])

    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [isEditing])

    const canEdit = privileged || actions.includes("edit")
    const canDelete = privileged || actions.includes("delete")
    const canManagePermission =
        privileged || actions.includes("manage_permission")

    const handleDoubleClick = () => {
        // Prefetch happened on hover; by the time a double-click lands the
        // action list is usually ready. Trigger once more in case it was not.
        ensureLoaded()
        if (canEdit) setIsEditing(true)
    }

    const handleBlur = (e) => {
        setIsEditing(false)
        const trimmedTitle = title.trim()

        if (!trimmedTitle) {
            // trimmedTitle = t('untitledDashboard')
            return setTitle(dashboard.title)
        }

        if (trimmedTitle.length > 200) {
            setTitle(dashboard.title)
            notification.open({ type: "error", description: String(t('charLimit200') ?? '') })
            return
        }

        if (canEdit && trimmedTitle !== dashboard.title) {
            onRename(dashboard.id, trimmedTitle)
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter") {
            inputRef.current?.blur()
        }
        if (e.key === "Escape") {
            setTitle(dashboard.title)
            setIsEditing(false)
        }
    }

    return (
        <div
            className={cn(
                "group flex items-center justify-between px-2 py-[6px] rounded-lg cursor-pointer transition-colors",
                selected ? "bg-[#002FFF]/10" : "hover:bg-[#f5f2f2f2]",
            )}
            onClick={onSelect}
            onMouseEnter={ensureLoaded}
        >
            <div className="flex-1 min-w-0 mr-2">
                {isEditing ? (
                    <Input ref={inputRef} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus={isEditing} onBlur={handleBlur} onKeyDown={handleKeyDown} onClick={(e) => e.stopPropagation()} className={"h-5 px-2 border-primary"} />
                ) : (
                    <div className={cn("truncate text-sm", selected && "text-primary")} title={dashboard.title} onDoubleClick={handleDoubleClick}>
                        {dashboard.title}
                    </div>
                )}
            </div>
            {permissionBadge}
            {dashboard.is_default && <Tag size="small" color="brand" className="shrink-0 whitespace-nowrap">{t('default')}</Tag>}

            <DropdownMenu onOpenChange={(open) => { if (open) ensureLoaded() }}>
                <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                    <Button variant="text" size="medium" aria-label="dashboard.actions" className={cn("h-5 w-5 shrink-0", isEditing
                            ? "invisible"
                            : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100")} color="default" iconOnly>
                        <Outlined.More className="h-4 w-4" />
                    </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {canEdit && appConfig.isDashboardPro && <DropdownMenuItem
                        onClick={() => setTimeout(() => {
                            setIsEditing(true)
                        }, 300)} // hold close dropdownmenu
                    >{t('rename')}</DropdownMenuItem>}
                    {appConfig.isDashboardPro && <DropdownMenuItem disabled={dashboard.is_default} onClick={() => onDefault(dashboard.id)}>{dashboard.is_default ? t('alreadyDefault') : t('setAsDefault')}</DropdownMenuItem>}
                    {appConfig.isDashboardPro && <DropdownMenuItem onClick={() => onDuplicate(dashboard)}>{t('duplicate')}</DropdownMenuItem>}
                    {canManagePermission && onPermission && <DropdownMenuItem onClick={() => onPermission(dashboard)}>{t('managePermission', { ns: 'permission' })}</DropdownMenuItem>}
                    <DropdownMenuItem onClick={() => onShare(dashboard.id)}>{t('share')}</DropdownMenuItem>
                    {canDelete && appConfig.isDashboardPro && <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => onDelete(dashboard.id)}>
                        {t('delete')}
                    </DropdownMenuItem>}
                </DropdownMenuContent>
            </DropdownMenu>
        </div >
    )
}
