// @ts-strict-ignore
import { Button, Input, notification } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import type React from "react";

import { Tooltip } from "@bisheng/ui";

import { Dialog,DialogContent,DialogDescription,DialogFooter,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import { Separator } from "@/components/bs-ui/separator";

import { updateDashboard } from "@/controllers/API/dashboard";
import { useComponentEditorStore,useEditorDashboardStore } from "@/store/dashboardStore";
import { Tag } from "@bisheng/ui";

import { useEffect,useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation,useQueryClient } from "react-query";
import { useNavigate } from "react-router-dom";
import { DashboardQueryKey,DashboardsQueryKey,usePublishDashboard } from "../../hook";
import { ChartType,Dashboard } from "../../types/dataConfig";
import ComponentPicker from "./ComponentPicker";


interface EditorHeaderProps {
    dashboard: Dashboard | null
    dashboardId: string
}

export function EditorHeader({
    dashboard,
    dashboardId
}: EditorHeaderProps) {
    const { t } = useTranslation("dashboard")
    const { currentDashboard, hasUnsavedChanges, lastChangeTime, isSaving, layouts,
        reset, setIsSaving, setHasUnsavedChanges, updateCurrentDashboard, addComponentToLayout } = useEditorDashboardStore()
    const { editingComponent } = useComponentEditorStore()
    const [isEditingTitle, setIsEditingTitle] = useState(false)
    const [title, setTitle] = useState(dashboard?.title || "")
    const inputRef = useRef<HTMLInputElement>(null)
    const queryClient = useQueryClient()


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
        onSuccess: (a, { autoSave, dashboard }, c) => {
            setHasUnsavedChanges(false)
            // refrensh react-query
            queryClient.invalidateQueries({ queryKey: [DashboardQueryKey, Number(dashboardId)] })
            queryClient.setQueryData([DashboardsQueryKey], (old) =>
                old.map(el => el.id === dashboard.id ? {
                    ...el,
                    title: dashboard.title,
                    status: dashboard.status,
                } : el));
            // queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            // autosave not require toast
            !autoSave && notification.open({ type: "success", description: String(t('saveSuccess') ?? '') })
        },
        onError: () => {
            notification.open({ type: "error", description: String(t('saveFailed') ?? '') })
        },
        onSettled: () => {
            setIsSaving(false)
        },
    })

    // Publish mutation
    const { publish, publishAsync, isPublishing } = usePublishDashboard()

    useDashboardAutoSave({
        currentDashboard,
        isSaving,
        hasUnsavedChanges,
        lastChangeTime,
        saveMutation
    })

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

        if (trimmedTitle !== dashboard.title) {
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
        await saveMutation.mutateAsync({
            id: currentDashboard?.id,
            dashboard: currentDashboard
        })
        reset()
        navigator(-1)
    }

    // Handle save
    const handleSave = async (e?) => {
        // if (!hasUnsavedChanges) {
        //     return
        // }
        // config -> crrentcompontent
        const querySave = document.querySelector('#query_save')
        const configSave = document.querySelector('#config_save')
        querySave?.click()
        configSave?.click()

        setTimeout(async () => {
            // currentDashboard.components.map(el => el.style_config.titleColor = '')
            await saveMutation.mutate({
                id: currentDashboard?.id,
                dashboard: currentDashboard,
                autoSave: !e
            })
        }, 300);
    }

    // Handle publish
    const handlePublish = async () => {
        // Trigger config/query component saves via DOM clicks
        const querySave = document.querySelector('#query_save') as HTMLElement | null
        const configSave = document.querySelector('#config_save') as HTMLElement | null
        querySave?.click()
        configSave?.click()

        // Wait for config sync to propagate to store
        await new Promise(resolve => setTimeout(resolve, 300))

        // Read the latest state directly from store (not from stale closure)
        const latestDashboard = useEditorDashboardStore.getState().currentDashboard
        const latestLayouts = useEditorDashboardStore.getState().layouts
        const editComp = useComponentEditorStore.getState().editingComponent

        // Save: await completion before proceeding
        await saveMutation.mutateAsync({
            id: latestDashboard?.id,
            dashboard: {
                ...latestDashboard,
                components: editComp
                    ? latestDashboard.components.map(c => c.id === editComp.id ? editComp : c)
                    : latestDashboard.components,
                layout_config: { layouts: latestLayouts }
            },
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
                <Tooltip content={t("bs:back")}><Button aria-label={t("bs:back")} variant="outlined" size="medium" className="min-w-9" onClick={handleExit} color="default" iconOnly>
                    <Outlined.ArrowLeft className="h-4 w-4" />
                </Button></Tooltip>
                <Separator orientation="vertical" className="bg-slate-300 h-4"></Separator>
                {isEditingTitle ? (
                    <Input ref={inputRef} value={title} onChange={(e) => setTitle(e.target.value)} onBlur={handleTitleBlur} onKeyDown={handleTitleKeyDown} className={"text-sm font-medium h-6 px-2 py-0 border-primary"} />
                ) : (
                    <h1
                        className="max-w-96 font-medium truncate cursor-pointer transition-colors"
                        title={title}
                        onDoubleClick={() => setIsEditingTitle(true)}
                    >
                        {title}
                    </h1>
                )}
                <Tag size="small" dot color={isSaving ? "brand" : hasUnsavedChanges ? "warning" : "success"} className="whitespace-nowrap">{getSaveStatus()}</Tag>
            </div>

            {/* Middle section */}
            <div className="flex items-center gap-4">
                {/* Add Component */}
                <ComponentPicker onSelect={addComponentToLayout}>
                    {useMemo(() => (
                        <Button variant="outlined" size="small" className="gap-1.5" color="default">
                            <Outlined.ViewGridCard className="size-4" />
                            {t('addChart')}
                        </Button>
                    ), [t])}
                </ComponentPicker>
                <Button variant="outlined" size="small" className="gap-1.5" onClick={() => addComponentToLayout({
                    title: t('selectDate'),
                    type: ChartType.Query
                })} color="default">
                    <Outlined.Filter className="size-4" />
                    {t('addQueryComponent')}
                </Button>
            </div>

            {/* Right section */}
            <div className="flex items-center gap-2">
                <Button variant="outlined" onClick={() => {
                    const element = document.getElementById('edit-charts-panne');
                    element.requestFullscreen();
                }} color="default">
                    {t('fullScreen')}
                </Button>
                <Button variant="outlined" disabled={isPublishing} onClick={handlePublish} color="default">
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
                        <Button className="leave" onClick={handleSaveAndClose}>
                            {t('saveAndLeave')}
                        </Button>
                        <Button variant="solid" onClick={() => navigator(-1)} color="danger">
                            {t('leaveWithoutSaving')}
                        </Button>
                        <Button variant="outlined" onClick={() => setLiveModalOpen(false)} color="default">
                            {t('cancel')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </header>
    )
}


export function useDashboardAutoSave({
    currentDashboard,
    isSaving,
    hasUnsavedChanges,
    lastChangeTime,
    saveMutation
}) {
    // --- Save at a fixed frequency of 15 seconds (Guaranteed Plan ) ---
    useEffect(() => {
        const idleTimer = setInterval(() => {
            if (hasUnsavedChanges && !isSaving) {
                console.log("Auto-saving dashboard...")
                saveMutation.mutate({
                    autoSave: true,
                    id: currentDashboard?.id,
                    dashboard: currentDashboard
                })
            }
        }, 15000)

        return () => clearInterval(idleTimer)
    }, [hasUnsavedChanges, isSaving])

    // --- Save after 2 seconds of inactivity (Idle/Debounce ) ---
    useEffect(() => {
        if (hasUnsavedChanges && !isSaving) {
            const idleTimer = setTimeout(() => {
                console.log("Log: 2s Idle Auto-save triggered.")
                saveMutation.mutate({
                    autoSave: true,
                    id: currentDashboard?.id,
                    dashboard: currentDashboard
                })
            }, 2000)
            return () => clearTimeout(idleTimer)
        }
    }, [hasUnsavedChanges, isSaving, lastChangeTime, saveMutation])
}