"use client"

import type React from "react"

import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Separator } from "@/components/bs-ui/separator"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { updateDashboard } from "@/controllers/API/dashboard"
import { useComponentEditorStore, useEditorDashboardStore } from "@/store/dashboardStore"
import { ArrowLeft, FunnelIcon, Grid2X2PlusIcon } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { useMutation, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { usePublishDashboard } from "../../hook"
import { ChartType, Dashboard } from "../../types/dataConfig"
import ComponentPicker from "./ComponentPicker"


interface EditorHeaderProps {
    dashboard: Dashboard | null
    dashboardId: string
}

export function EditorHeader({
    dashboard,
    dashboardId,
}: EditorHeaderProps) {
    const { t } = useTranslation("dashboard")
    const { currentDashboard, hasUnsavedChanges, isSaving, layouts,
        reset, setIsSaving, setHasUnsavedChanges, addComponentToLayout } = useEditorDashboardStore()
    const { editingComponent } = useComponentEditorStore()
    const [isEditingTitle, setIsEditingTitle] = useState(false)
    const [title, setTitle] = useState(dashboard?.title || "")
    const inputRef = useRef<HTMLInputElement>(null)
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
        mutationFn: ({ id, dashboard }: any) => updateDashboard(id, {
            ...dashboard,
            components: editingComponent ? dashboard.components.map(com =>
                com.id === editingComponent.id ? editingComponent : com
            ) : dashboard.components,
            layout_config: { layouts }
        }),
        onMutate: () => {
            setIsSaving(true)
        },
        onSuccess: (a, { autoSave }, c) => {
            setHasUnsavedChanges(false)
            queryClient.invalidateQueries({ queryKey: ["dashboard", dashboardId] })
            queryClient.invalidateQueries({ queryKey: ["dashboards"] })
            // autosave not require toast
            !autoSave && toast({
                description: t('saveSuccess'),
                variant: "success",
            })
        },
        onError: () => {
            toast({
                description: t('saveFailed'),
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
                    console.log("Auto-saving dashboard...")
                    saveMutation.mutate({
                        autoSave: true,
                        id: currentDashboard?.id,
                        dashboard: currentDashboard
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
        if (isSaving) return t('saving')
        if (hasUnsavedChanges) return t('unsaved')
        return t('saved')
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
        } else {
            reset()
            navigator(-1)
        }
    }
    const handleSaveAndClose = async () => {
        await saveMutation.mutateAsync({
            id: currentDashboard?.id,
            dashboard: currentDashboard
        })
        reset()
        navigator(-1)
    }

    // Handle save
    const handleSave = async () => {
        // if (!hasUnsavedChanges) {
        //     return
        // }
        // config -> crrentcompontent
        const querySave = document.querySelector('#query_save')
        const configSave = document.querySelector('#config_save')
        querySave?.click()
        configSave?.click()

        setTimeout(async () => {
            await saveMutation.mutate({
                id: currentDashboard?.id,
                dashboard: currentDashboard
            })
        }, 300);
    }

    // Handle publish
    const handlePublish = async () => {
        // If has unsaved changes, save first
        await handleSave()

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
                        className="max-w-96 font-medium truncate cursor-pointer transition-colors"
                        title={dashboard?.title}
                    // onDoubleClick={handleTitleDoubleClick}
                    >
                        {dashboard?.title}
                    </h1>
                )}
                <Badge variant="outline" className=" font-normal bg-gray-100">{getSaveStatus()}</Badge>
            </div>

            {/* Middle section */}
            <div className="flex items-center gap-4">
                {/* Add Component */}
                <ComponentPicker onSelect={addComponentToLayout}>
                    <Button variant="outline" size="sm" className="gap-2">
                        <Grid2X2PlusIcon size="14" />
                        {t('addChart')}
                    </Button>
                </ComponentPicker>
                <Button variant="outline" size="sm" className="gap-2" onClick={() => addComponentToLayout({
                    title: "",
                    type: ChartType.Query
                })}>
                    <FunnelIcon size="14" />
                    {t('addQueryComponent')}
                </Button>
            </div>

            {/* Right section */}
            <div className="flex items-center gap-2">
                <Button variant="outline" onClick={() => {
                    const element = document.getElementById('edit-charts-panne');
                    element.requestFullscreen();
                }}>
                    {t('fullScreen')}
                </Button>
                <Button variant="outline" disabled={isPublishing} onClick={handlePublish}>
                    {t('saveAndPublish')}
                </Button>
                <Button onClick={handleSave} disabled={saveMutation.isLoading}>
                    {t('save')}
                </Button>
            </div>

            <Dialog open={liveModalOpen}>
                <DialogContent className="sm:max-w-[425px]" close={false}>
                    <DialogHeader>
                        <DialogTitle>{t('prompt')}</DialogTitle>
                        <DialogDescription>{t('unsavedChangesWarning')}</DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button className="leave h-8" onClick={handleSaveAndClose}>
                            {t('saveAndLeave')}
                        </Button>
                        <Button className="h-8" variant="destructive" onClick={() => navigator(-1)}>
                            {t('leaveWithoutSaving')}
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
