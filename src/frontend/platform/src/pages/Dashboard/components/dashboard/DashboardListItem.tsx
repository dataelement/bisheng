"use client"

import type React from "react"

import { Button } from "@/components/bs-ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { cn } from "@/utils"
import { MoreHorizontal } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Dashboard } from "../../types/dataConfig"


interface DashboardListItemProps {
    dashboard: Dashboard
    selected: boolean
    onSelect: () => void
    onRename: (id: string, newTitle: string) => void
    onDuplicate: (id: string) => void
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
    onDelete,
}: DashboardListItemProps) {
    const [isEditing, setIsEditing] = useState(false)
    const [title, setTitle] = useState(dashboard.title)
    const inputRef = useRef<HTMLInputElement>(null)
    const { toast } = useToast()

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
        const trimmedTitle = title.trim()

        if (!trimmedTitle) {
            setTitle(dashboard.title)
            toast({
                description: "名称不能为空",
                variant: "error",
            })
            return
        }

        if (trimmedTitle.length < 1 || trimmedTitle.length > 200) {
            setTitle(dashboard.title)
            toast({
                description: "字数范围 1-200 字",
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
                "group flex items-center justify-between px-3 py-2 rounded-md cursor-pointer hover:bg-accent transition-colors",
                selected && "bg-accent",
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
                        className="h-7 px-2"
                        onClick={(e) => e.stopPropagation()}
                    />
                ) : (
                    <div className="truncate text-sm" title={dashboard.title} onDoubleClick={handleDoubleClick}>
                        {dashboard.title}
                    </div>
                )}
            </div>

            <DropdownMenu>
                <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                    <Button variant="ghost" size="icon" className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity">
                        <MoreHorizontal className="h-4 w-4" />
                    </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {!dashboard.mange && <DropdownMenuItem onClick={() => setIsEditing(true)}>重命名</DropdownMenuItem>}
                    {!dashboard.mange && <DropdownMenuItem onClick={() => onDuplicate(dashboard.id)}>复制</DropdownMenuItem>}
                    {!dashboard.view && <DropdownMenuItem onClick={() => onShare(dashboard.id)}>分享</DropdownMenuItem>}
                    {!dashboard.mange && <DropdownMenuItem className="text-destructive" onClick={() => onDelete(dashboard.id)}>
                        删除
                    </DropdownMenuItem>}
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
