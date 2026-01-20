"use client"

import type React from "react"

import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { locationContext } from "@/contexts/locationContext"
import { cn } from "@/utils"
import { MoreHorizontal } from "lucide-react"
import { useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Dashboard } from "../../types/dataConfig"


interface DashboardListItemProps {
    dashboard: Dashboard
    selected: boolean
    onSelect: () => void
    onRename: (id: string, newTitle: string) => void
    onDuplicate: (dashboard: Dashboard) => void
    onDefault: (id: string) => void
    onShare: (id: string) => void
    onDelete: (id: string) => void
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
}: DashboardListItemProps) {
    const { t } = useTranslation("dashboard")

    const [isEditing, setIsEditing] = useState(false)
    const [title, setTitle] = useState('')
    const inputRef = useRef<HTMLInputElement>(null)
    const { toast } = useToast()
    const { appConfig } = useContext(locationContext)

    useEffect(() => {
        setTitle(dashboard.title)
    }, [dashboard])

    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [isEditing])

    const handleDoubleClick = () => {
        !dashboard.mange && setIsEditing(true)
    }

    const handleBlur = () => {
        setIsEditing(false)
        let trimmedTitle = title.trim()

        if (!trimmedTitle) {
            // trimmedTitle = t('untitledDashboard')
            return setTitle(dashboard.title)
        }

        if (trimmedTitle.length > 200) {
            setTitle(dashboard.title)
            toast({
                description: t('charLimit200'),
                variant: "error",
            })
            return
        }

        if (trimmedTitle !== dashboard.title) {
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
        >
            <div className="flex-1 min-w-0 mr-2">
                {isEditing ? (
                    <Input
                        ref={inputRef}
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        onBlur={handleBlur}
                        onKeyDown={handleKeyDown}
                        className="h-5 px-2 border-primary"
                        onClick={(e) => e.stopPropagation()}
                    />
                ) : (
                    <div className={cn("truncate text-sm", selected && "text-primary")} title={dashboard.title} onDoubleClick={handleDoubleClick}>
                        {dashboard.title}
                    </div>
                )}
            </div>
            {dashboard.is_default && <Badge variant="outline" className="border border-primary rounded-sm py-0 px-1 text-primary scale-75">{t('default')}</Badge>}

            <DropdownMenu>
                <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                    <Button variant="ghost" size="icon" className={`h-5 w-0 ${isEditing ? "" : "group-hover:w-5"}`}>
                        <MoreHorizontal className="h-4 w-4" />
                    </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {dashboard.write && appConfig.isPro && <DropdownMenuItem onClick={() => setIsEditing(true)}>{t('rename')}</DropdownMenuItem>}
                    {appConfig.isPro && <DropdownMenuItem disabled={dashboard.is_default} onClick={() => onDefault(dashboard.id)}>{dashboard.is_default ? t('alreadyDefault') : t('setAsDefault')}</DropdownMenuItem>}
                    {dashboard.write && appConfig.isPro && <DropdownMenuItem onClick={() => onDuplicate(dashboard)}>{t('duplicate')}</DropdownMenuItem>}
                    <DropdownMenuItem onClick={() => onShare(dashboard.id)}>{t('share')}</DropdownMenuItem>
                    {dashboard.write && appConfig.isPro && <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => onDelete(dashboard.id)}>
                        {t('delete')}
                    </DropdownMenuItem>}
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
