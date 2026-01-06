"use client"

import type React from "react"

import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { getShareLink, updateDashboard } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { cn, copyText } from "@/utils"
import { ArrowLeft, Eye, FunnelIcon, Grid2X2PlusIcon, Maximize, Pencil, Plus, Share2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { useMutation, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { usePublishDashboard } from "../../hook"
import ComponentPicker from "./ComponentPicker"
import ThemePicker from "./ThemePicker"
import { Dashboard } from "../../types/dataConfig"
import { Separator } from "@/components/bs-ui/separator"
import { Badge } from "@/components/bs-ui/badge"


interface EditorHeaderProps {
    dashboard: Dashboard | null
    dashboardId: string
}

export function EditorHeader({
    dashboard,
    dashboardId,
}: EditorHeaderProps) {
    const { hasUnsavedChanges, isSaving, reset, setIsSaving, setHasUnsavedChanges } = useEditorDashboardStore()
    const [isEditingTitle, setIsEditingTitle] = useState(false)
    const [title, setTitle] = useState(dashboard?.title || "")
    const inputRef = useRef<HTMLInputElement>(null)
    const { t } = useTranslation()
    const queryClient = useQueryClient()
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

    // Save mutation
    const saveMutation = useMutation({
        mutationFn: (data: any) => updateDashboard(dashboardId, data),
        onMutate: () => {
            setIsSaving(true)
        },
        onSuccess: (a, { autoSave }, c) => {
            setHasUnsavedChanges(false)
            queryClient.invalidateQueries({ queryKey: ["dashboard", dashboardId] })
            queryClient.invalidateQueries({ queryKey: ["dashboards"] })
            // autosave not require toast
            !autoSave && toast({
                description: "保存成功",
                variant: "success",
            })
        },
        onError: () => {
            toast({
                description: "保存失败",
                variant: "error",
            })
        },
        onSettled: () => {
            setIsSaving(false)
        },
    })

    // Publish mutation
    const { publish, isPublishing } = usePublishDashboard()

    // Auto-save every 10 seconds
    const autoSaveTimerRef = useRef<NodeJS.Timeout>()
    useEffect(() => {
        const startAutoSave = () => {
            autoSaveTimerRef.current = setInterval(() => {
                if (hasUnsavedChanges && !isSaving) {
                    console.log("[v0] Auto-saving dashboard...")
                    saveMutation.mutate({
                        autoSave: true
                        // data
                    })
                }
            }, 10000)
        }

        startAutoSave()

        return () => {
            if (autoSaveTimerRef.current) {
                clearInterval(autoSaveTimerRef.current)
            }
        }
    }, [hasUnsavedChanges, isSaving, saveMutation])

    const getSaveStatus = () => {
        if (isSaving) return "保存中..."
        if (hasUnsavedChanges) return "未保存"
        return "已保存"
    }

    const getSaveStatusColor = () => {
        if (isSaving) return "text-blue-600"
        if (hasUnsavedChanges) return "text-amber-600"
        return "text-green-600"
    }

    const handleTitleDoubleClick = () => {
        if (dashboard) {
            setIsEditingTitle(true)
        }
    }

    const handleTitleBlur = () => {
        // setIsEditingTitle(false)
        // const trimmedTitle = title.trim()

        // if (!trimmedTitle || !dashboard) {
        //     setTitle(dashboard?.title || "")
        //     return
        // }

        // if (trimmedTitle !== dashboard.title) {
        //     onTitleChange(trimmedTitle)
        // }
    }

    const handleTitleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter") {
            inputRef.current?.blur()
        }
        if (e.key === "Escape") {
            setTitle(dashboard?.title || "")
            setIsEditingTitle(false)
        }
    }

    const navigator = useNavigate()
    const [liveModalOpen, setLiveModalOpen] = useState(false)
    const handleExit = () => {

        if (hasUnsavedChanges) {
            setLiveModalOpen(true)
            // bsConfirm({
            //     desc: "当前有未保存的修改",
            //     okTxt: "保存并退出",
            //     cancelTxt: "不保存退出",
            //     showThirdButton: true,
            //     thirdButtonTxt: "取消",
            //     onOk: async (next) => {
            //         await saveMutation.mutateAsync({})
            //         reset()
            //         navgator(`/?selected=${dashboardId}`)
            //         next()
            //     },
            // onCancel: (next) => {
            //     reset()
            //     navgator(`/?selected=${dashboardId}`)
            //     next()
            // },
            // })
        } else {
            reset()
            navigator(-1)
        }
    }
    const handleSaveAndClose = async () => {
        await saveMutation.mutateAsync({
            // TODO 需要保存的数据
        })
        reset()
        navigator(-1)
    }

    // Handle add component
    const handleAddComponent = (type: string) => {
        console.log("[v0] Adding component:", type)
        setHasUnsavedChanges(true)
        toast({
            description: `添加${type}组件功能开发中...`,
        })
    }

    // Handle theme change
    const handleThemeChange = (theme: string) => {
        console.log("[v0] Changing theme:", theme)
        setHasUnsavedChanges(true)
        toast({
            description: `切换主题功能开发中...`,
        })
    }

    // Handle save
    const handleSave = () => {
        // if (!hasUnsavedChanges) {
        //     return
        // }

        saveMutation.mutate({
            // todo data
        })
    }

    // Handle publish
    const handlePublish = async () => {
        // If has unsaved changes, save first
        if (hasUnsavedChanges) {
            await saveMutation.mutateAsync({})
        }

        publish(dashboard.id, false)
        navigator(`/dashboard?selected=${dashboardId}`)
    }

    // Reset store on unmount
    useEffect(() => {
        return () => {
            reset()
        }
    }, [reset])

    return (
        <header className="h-16 border-b bg-background flex items-center justify-between px-4 py-3.5">
            {/* Left section */}
            <div className="flex items-center gap-4">
                <Button variant="outline" size="icon" onClick={handleExit}>
                    <ArrowLeft className="h-4 w-4" />
                </Button>
                <Separator orientation="vertical" className="bg-slate-300 h-4"></Separator>
                {isEditingTitle ? (
                    <Input
                        ref={inputRef}
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        onBlur={handleTitleBlur}
                        onKeyDown={handleTitleKeyDown}
                        className="text-sm font-medium h-6 px-2 py-0"
                    />
                ) : (
                    <h1
                        className="font-medium truncate cursor-pointer transition-colors"
                        title={dashboard?.title}
                    // onDoubleClick={handleTitleDoubleClick}
                    >
                        {dashboard?.title || "未命名看板"}
                    </h1>
                )}
                <Badge variant="outline" className=" font-normal bg-gray-100">{getSaveStatus()}</Badge>
            </div>

            {/* Middle section */}
            <div className="flex items-center gap-4">
                {/* Add Component */}
                <ComponentPicker >
                    <Button variant="outline" size="sm" className="gap-2">
                        <Grid2X2PlusIcon size="14" />
                        添加图表
                    </Button>
                </ComponentPicker>
                <Button variant="outline" size="sm" className="gap-2">
                    <FunnelIcon size="14" />
                    添加查询组件
                </Button>
            </div>

            {/* Right section */}
            <div className="flex items-center gap-2">
                <Button variant="outline" onClick={() => {
                    const element = document.getElementById('edit-charts-panne');
                    element.requestFullscreen();
                }}>
                    全屏
                </Button>
                <Button variant="outline" disabled={isPublishing} onClick={handlePublish}>
                    保存并发布
                </Button>
                <Button onClick={handleSave} disabled={isSaving}>
                    保存
                </Button>
            </div>

            <Dialog open={liveModalOpen}>
                <DialogContent className="sm:max-w-[425px]" close={false}>
                    <DialogHeader>
                        <DialogTitle>{t('prompt')}</DialogTitle>
                        <DialogDescription>{'您有未保存的更改,确定要离开吗?'}</DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button className="leave h-8" onClick={handleSaveAndClose}>
                            {t('flow.leaveAndSave')}
                        </Button>
                        <Button className="h-8" variant="destructive" onClick={() => navigator(-1)}>
                            {t('build.leaveWithoutSave')}
                        </Button>
                        <Button className="h-8" variant="outline" onClick={() => setLiveModalOpen(false)}>
                            {t('cancel')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </header>
    )
}
