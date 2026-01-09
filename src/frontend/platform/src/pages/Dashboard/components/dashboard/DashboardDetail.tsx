"use client"

import type React from "react"

import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import Tip from "@/components/bs-ui/tooltip/tip"
import { locationContext } from "@/contexts/locationContext"
import { userContext } from "@/contexts/userContext"
import { CircleAlert, Edit, Eye, EyeOff, Maximize2, Share2 } from "lucide-react"
import { useContext, useEffect, useRef, useState } from "react"
import { DashboardStatus, usePublishDashboard } from "../../hook"
import { Dashboard } from "../../types/dataConfig"
import { EditorCanvas } from "../editor/EditorCanvas"
import { ButtonGroup } from "@/components/bs-ui/button/group"

interface DashboardDetailProps {
    dashboard: Dashboard | null
    isLoading: boolean
    onRename: (id: string, newTitle: string) => void
    onShare: (id: string) => void
    onDefault: (id: string) => void
    onEdit: (id: string) => void
}

export function DashboardDetail({
    dashboard,
    isLoading,
    onRename,
    onDefault,
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
        if (appConfig.isPro && dashboard.write) {
            setIsEditingTitle(true)
        }
    }

    const handleBlur = () => {
        setIsEditingTitle(false)
        const trimmedTitle = title.trim()

        if (!trimmedTitle || !dashboard) {
            setTitle(dashboard?.title || "")
            return toast({
                description: "名称不能为空",
                variant: "error",
            })
        }

        if (trimmedTitle.length > 200) {
            setTitle(dashboard.title)
            return toast({
                description: "字数范围 1-200 字",
                variant: "error",
            })
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
            <div className="border-b px-4 py-3 h-[52px] flex items-center justify-between">
                <div className="flex items-center gap-4 flex-1 min-w-0">
                    <div className="flex-1 min-w-0 flex items-center">
                        {isEditingTitle ? (
                            <Input
                                ref={inputRef}
                                value={title}
                                onChange={(e) => setTitle(e.target.value)}
                                onBlur={handleBlur}
                                onKeyDown={handleKeyDown}
                                boxClassName="w-auto"
                                className="max-w-96 text-xl font-semibold h-6 px-2 py-1 border-primary"
                            />
                        ) : (
                            <h1
                                className="max-w-96 text-base font-semibold truncate cursor-pointer hover:text-primary transition-colors"
                                title={dashboard.title}
                                onDoubleClick={handleDoubleClick}
                            >
                                {dashboard.title}
                            </h1>
                        )}
                        {appConfig.isPro && <>
                            <p className="text-sm ml-4 mr-2">
                                <span className="text-muted-foreground">创建人：</span>
                                {dashboard.user_name}</p>
                            <Tip
                                styleClasses="bg-white text-gary-400 border"
                                content={
                                    <div >
                                        <p className="text-sm text-gray-500">创建人：</p>
                                        <p className="text-sm mb-1.5">{dashboard.user_name}</p>
                                        <p className="text-sm text-gray-500">创建时间：</p>
                                        <p className="text-sm mb-1.5">{dashboard.create_time.replace('T', ' ')}</p>
                                        <p className="text-sm text-gray-500">最近更新时间：</p>
                                        <p className="text-sm mb-1.5">{dashboard.update_time.replace('T', ' ')}</p>
                                    </div>
                                }
                                side={'bottom'}>
                                <CircleAlert color="#999" size={16} className="cursor-pointer" />
                            </Tip>
                        </>}
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <ButtonGroup>
                        <Button variant="outline" size="sm" onClick={handleFullscreen}>全屏</Button>
                        {dashboard.write && <Button variant="outline" size="sm" onClick={() => publish(dashboard.id, isPublished)}>{isPublished ? '取消发布' : '发布'}</Button>}
                        <Button variant="outline" size="sm" onClick={() => onShare(dashboard.id)}>分享</Button>
                    </ButtonGroup>

                    {appConfig.isPro && <Button
                        variant="outline"
                        className="disabled:pointer-events-auto"
                        disabled={dashboard.is_default}
                        size="sm"
                        onClick={() => onDefault(dashboard.id)}>
                        {dashboard.is_default ? '已设为默认' : '设为默认'}
                    </Button>}

                    {appConfig.isPro && dashboard.write &&
                        <Tip content={isPublished ? "取消发布后方可编辑" : ""} side={"top"} styleClasses="-translate-x-12" >
                            <Button
                                className="disabled:pointer-events-auto"
                                disabled={isPublished}
                                size="sm"
                                onClick={() => onEdit(dashboard.id)}>
                                编辑看板
                            </Button>
                        </Tip>
                    }
                </div>
            </div>

            <div id="view-panne" className="flex-1 overflow-auto">
                <EditorCanvas isPreviewMode isLoading={isLoading} dashboard={dashboard || null} />
            </div>
        </div>
    )
}
