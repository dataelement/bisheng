"use client"

import type React from "react"

import { FilterIcon, GridAddIcon } from "@/components/bs-icons/dashboard"
import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Separator } from "@/components/bs-ui/separator"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { updateDashboard } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { ArrowLeft } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { useMutation, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { DashboardQueryKey, DashboardsQueryKey, usePublishDashboard } from "../../hook"
import { ChartType, Dashboard } from "../../types/dataConfig"
import ComponentPicker from "./ComponentPicker"


interface EditorHeaderProps {
    dashboard: Dashboard | null
    dashboardId: string
}

export function EditorHeader({
    dashboard,
    dashboardId
}: EditorHeaderProps) {
    const { t } = useTranslation("dashboard")
    const {
        currentDashboard,
        hasUnsavedChanges,
        isSaving,
        reset,
        setIsSaving,
        updateCurrentDashboard,
        markDashboardSaved,
        addComponentToLayout,
    } = useEditorDashboardStore()
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
        mutationFn: ({ id, dashboard }: any) => updateDashboard(id, dashboard),
        onMutate: () => {
            setIsSaving(true)
        },
        onSuccess: (_response, { dashboard }) => {
            markDashboardSaved(dashboard)
            // refrensh react-query
            queryClient.invalidateQueries({ queryKey: [DashboardQueryKey, Number(dashboardId)] })
            queryClient.setQueryData([DashboardsQueryKey], (old) =>
                old.map(el => el.id === dashboard.id ? {
                    ...el,
                    title: dashboard.title,
                    status: dashboard.status,
                } : el));
            // queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            toast({
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
    const { publishAsync, isPublishing } = usePublishDashboard()

    const getSaveStatus = () => {
        if (isSaving) return t('saving')
        if (hasUnsavedChanges) return t('unsaved')
        return t('saved')
    }

    const handleTitleBlur = () => {
        setIsEditingTitle(false)
        const trimmedTitle = title.trim()

        if (!trimmedTitle) {
            return setTitle(dashboard?.title || "")
        }

        if (trimmedTitle !== currentDashboard?.title) {
            setTitle(trimmedTitle)
            updateCurrentDashboard({ ...currentDashboard, title: trimmedTitle })
        }
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
        const dashboardDraft = getCurrentDashboardDraft()
        if (!dashboardDraft) return
        await saveMutation.mutateAsync({
            id: dashboardDraft.id,
            dashboard: dashboardDraft,
        })
        reset()
        navigator(-1)
    }

    const getCurrentDashboardDraft = () => {
        const state = useEditorDashboardStore.getState()
        if (!state.currentDashboard) return null
        return {
            ...state.currentDashboard,
            layout_config: {
                ...state.currentDashboard.layout_config,
                layouts: state.layouts,
            },
        }
    }

    // Handle save
    const handleSave = async () => {
        const dashboardDraft = getCurrentDashboardDraft()
        if (!dashboardDraft) return
        await saveMutation.mutateAsync({
            id: dashboardDraft.id,
            dashboard: dashboardDraft,
        })
    }

    // Handle publish
    const handlePublish = async () => {
        const dashboardDraft = getCurrentDashboardDraft()
        if (!dashboardDraft) return

        // Save: await completion before proceeding
        await saveMutation.mutateAsync({
            id: dashboardDraft.id,
            dashboard: dashboardDraft,
        })

        // Publish: await completion before navigating
        await publishAsync(dashboard.id, false)

        // Clear stale cache so the list page fetches fresh data with published status.
        // This prevents the save mutation's background refetch from overwriting the
        // published status with the old "draft" value.
        queryClient.removeQueries({ queryKey: [DashboardQueryKey, Number(dashboardId)] })
        queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })

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
                <Button variant="outline" size="icon" className="min-w-9" onClick={handleExit}>
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
                        className="text-sm font-medium h-6 px-2 py-0 border-primary"
                    />
                ) : (
                    <h1
                        className="max-w-96 font-medium truncate cursor-pointer transition-colors"
                        title={title}
                        onDoubleClick={() => setIsEditingTitle(true)}
                    >
                        {title}
                    </h1>
                )}
                <Badge variant="outline" className="break-keep font-normal bg-gray-100 dark:bg-black">{getSaveStatus()}</Badge>
            </div>

            {/* Middle section */}
            <div className="flex items-center gap-4">
                {/* Add Component */}
                <ComponentPicker onSelect={addComponentToLayout}>
                    {useMemo(() => (
                        <Button variant="outline" size="sm" className="gap-1.5">
                            <GridAddIcon className="size-4" />
                            {t('addChart')}
                        </Button>
                    ), [t])}
                </ComponentPicker>
                <Button variant="outline" size="sm" className="gap-1.5" onClick={() => addComponentToLayout({
                    title: t('selectDate'),
                    type: ChartType.Query
                })}>
                    <FilterIcon className="size-4" />
                    {t('addQueryComponent')}
                </Button>
                <Button variant="outline" size="sm" className="gap-1.5" onClick={() => addComponentToLayout({
                    title: t('dimensionFilter.title', '组合筛选'),
                    type: ChartType.DimensionFilter
                })}>
                    <FilterIcon className="size-4" />
                    {t('dimensionFilter.add', '添加维度筛选')}
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
