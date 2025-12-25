"use client"

import type React from "react"

import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import Tip from "@/components/bs-ui/tooltip/tip"
import { locationContext } from "@/contexts/locationContext"
import { userContext } from "@/contexts/userContext"
import { type Dashboard } from "@/controllers/API/dashboard"
import { Edit, Eye, EyeOff, Maximize2, Share2 } from "lucide-react"
import { useContext, useEffect, useRef, useState } from "react"
import { DashboardStatus, usePublishDashboard } from "../../hook"
import { EditorCanvas } from "../editor/EditorCanvas"

interface DashboardDetailProps {
    dashboard: Dashboard | null
    onRename: (id: string, newTitle: string) => void
    onShare: (id: string) => void
    onEdit: (id: string) => void
}

export function DashboardDetail({
    dashboard,
    onRename,
    onShare,
    onEdit
}: DashboardDetailProps) {
    const [isEditingTitle, setIsEditingTitle] = useState(false)
    const [title, setTitle] = useState(dashboard?.title || "")
    const inputRef = useRef<HTMLInputElement>(null)
    const { appConfig } = useContext(locationContext)
    const { user } = useContext(userContext);
    const isAdmin = user.role === 'admin'
    const { toast } = useToast()

    useEffect(() => {
        if (dashboard) {
            setTitle(dashboard.title)
        }
    }, [dashboard])

    useEffect(() => {
        if (isEditingTitle && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [isEditingTitle])

    const handleDoubleClick = () => {
        if (dashboard) {
            setIsEditingTitle(true)
        }
    }

    const handleBlur = () => {
        setIsEditingTitle(false)
        const trimmedTitle = title.trim()

        if (!trimmedTitle || !dashboard) {
            setTitle(dashboard?.title || "")
            return
        }

        if (trimmedTitle.length < 1 || trimmedTitle.length > 200) {
            setTitle(dashboard.title)
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
            setTitle(dashboard?.title || "")
            setIsEditingTitle(false)
        }
    }

    const handleFullscreen = () => {
        const element = document.getElementById('view-panne');
        element.requestFullscreen();
    }


    const { publish } = usePublishDashboard()

    if (!dashboard) {
        return <div className="flex-1 flex items-center justify-center text-muted-foreground">请选择一个看板</div>
    }
    const isPublished = dashboard.status === DashboardStatus.Published
    console.log('dashboard :>> ', dashboard);

    return (
        <div className="flex-1 flex flex-col h-full">
            <div className="border-b px-6 py-2 flex items-center justify-between">
                <div className="flex items-center gap-4 flex-1 min-w-0">
                    <div className="flex-1 min-w-0">
                        {isEditingTitle ? (
                            <Input
                                ref={inputRef}
                                value={title}
                                onChange={(e) => setTitle(e.target.value)}
                                onBlur={handleBlur}
                                onKeyDown={handleKeyDown}
                                className="max-w-96 text-xl font-semibold h-auto px-2 py-1"
                            />
                        ) : (
                            <h1
                                className="max-w-96 text-xl font-semibold truncate cursor-pointer hover:text-primary transition-colors"
                                title={dashboard.title}
                                onDoubleClick={handleDoubleClick}
                            >
                                {dashboard.title}
                            </h1>
                        )}
                        <p className="text-sm text-muted-foreground mt-1">创建人：{dashboard.created_by || "未知"}</p>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={handleFullscreen}>
                        <Maximize2 className="h-4 w-4 mr-2" />
                        全屏
                    </Button>

                    {appConfig.isPro && isAdmin &&
                        <Tip content={isPublished ? "取消发布后方可编辑" : ""} side={"top"} >
                            <Button
                                variant="outline"
                                className="disabled:pointer-events-auto"
                                disabled={isPublished}
                                size="sm"
                                onClick={() => onEdit(dashboard.id)}>
                                <Edit className="h-4 w-4 mr-2" />
                                编辑
                            </Button>
                        </Tip>
                    }

                    {isAdmin && <Button variant="outline" size="sm" onClick={() => publish(dashboard.id, isPublished)}>
                        {isPublished ? (
                            <>
                                <EyeOff className="h-4 w-4 mr-2" />
                                取消发布
                            </>
                        ) : (
                            <>
                                <Eye className="h-4 w-4 mr-2" />
                                发布
                            </>
                        )}
                    </Button>}

                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onShare(dashboard.id)}
                    >
                        <Share2 className="h-4 w-4 mr-2" />
                        分享
                    </Button>
                </div>
            </div>

            <div id="view-panne" className="flex-1 overflow-auto">
                <EditorCanvas isPreviewMode dashboard={dashboard || null} />
            </div>
        </div>
    )
}
