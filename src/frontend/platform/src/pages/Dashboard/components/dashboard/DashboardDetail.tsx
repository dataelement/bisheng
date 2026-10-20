// @ts-strict-ignore
import { Button, Input, notification } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import type React from "react";


import { ButtonGroup } from "@/components/bs-ui/button/group";


import { locationContext } from "@/contexts/locationContext";
import { Tooltip as Tip } from "@bisheng/ui";

import { LoadingIcon } from "@/components/bs-icons/loading";
import { useContext,useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import {
DashboardStatus,
useDashboardPermissions,
usePublishDashboard,
} from "../../hook";
import { Dashboard } from "../../types/dataConfig";
import { EditorCanvas } from "../editor/EditorCanvas";

interface DashboardDetailProps {
    dashboard: Dashboard | null
    isLoading: boolean
    isCollapsed: boolean
    setIsCollapsed: (isCollapsed: boolean) => void
    onRename: (id: string, newTitle: string) => void
    onShare: (id: string) => void
    onDefault: (id: string) => void
    onEdit: (id: string) => void
}

export function DashboardDetail({
    dashboard,
    isLoading,
    isCollapsed,
    setIsCollapsed,
    onRename,
    onDefault,
    onShare,
    onEdit
}: DashboardDetailProps) {
    const { t } = useTranslation("dashboard")

    const [isEditingTitle, setIsEditingTitle] = useState(false)
    const [title, setTitle] = useState(dashboard?.title || "")
    const inputRef = useRef<HTMLInputElement>(null)
    const { appConfig } = useContext(locationContext)

    const dashboardId = dashboard ? String(dashboard.id) : ""
    const {
        permissions,
        loading: permissionsLoading,
        privileged,
    } = useDashboardPermissions(dashboardId ? [dashboardId] : [])
    const permissionActions = permissions[dashboardId] ?? []
    // A successful my-permissions lookup is the visibility signal; the endpoint
    // refuses the request outright when the resource is not visible.
    const canView = privileged || Object.hasOwn(permissions, dashboardId)
    const canEdit = privileged || permissionActions.includes("edit")

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
        if (appConfig.isDashboardPro && canEdit) {
            setIsEditingTitle(true)
        }
    }

    const handleBlur = () => {
        setIsEditingTitle(false)
        const trimmedTitle = title.trim()

        if (!trimmedTitle || !dashboard) {
            return setTitle(dashboard?.title || "")
            // return toast({
            //     description: t('nameRequired'),
            //     variant: "error",
            // })
        }

        if (trimmedTitle.length > 200) {
            setTitle(dashboard.title)
            return notification.open({ type: "error", description: String(t('charLimit200') ?? '') })
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

    if (isLoading || permissionsLoading) {
        return <div className="flex-1 flex justify-center items-center z-10">
            <LoadingIcon />
        </div>
    }

    if (!dashboard) {
        return <div className="flex-1 flex items-center justify-center text-muted-foreground">{t('selectADashboard')}</div>
    }
    if (!canView) return null

    const isPublished = dashboard.status === DashboardStatus.Published

    return (
        <div className="flex-1 flex flex-col h-full min-w-0">
            <div className="border-b px-4 py-3 h-[52px] flex items-center justify-between">
                <div className="flex items-center gap-4 flex-1 min-w-0">
                    <div className="flex-1 min-w-0 flex items-center">
                        {isCollapsed && <Tip content={t('expandList')}>
                            <Button variant="text" size="medium" className={"hover:text-primary bg-background mr-4"} onClick={() => setIsCollapsed(!isCollapsed)} color="default" iconOnly>
                                <Outlined.SidebarMenu className="h-4 w-4 hover:text-primary" />
                            </Button>
                        </Tip>}
                        {isEditingTitle ? (
                            <Input ref={inputRef} value={title} onChange={(e) => setTitle(e.target.value)} onBlur={handleBlur} onKeyDown={handleKeyDown} className={["w-auto", "max-w-96 text-base font-semibold h-6 px-2 py-1 border-primary"].filter(Boolean).join(" ")} />
                        ) : (
                            <h1
                                className="max-w-96 text-base font-semibold truncate cursor-pointer hover:text-primary transition-colors"
                                title={dashboard.title}
                                onDoubleClick={handleDoubleClick}
                            >
                                {dashboard.title}
                            </h1>
                        )}
                        {appConfig.isDashboardPro && <>
                            <p className="text-sm ml-4 mr-2">
                                <span className="text-muted-foreground">{t('createdBy')}: </span>
                                {dashboard.user_name}</p>
                            <Tip

                                content={
                                    <div >
                                        <p className="text-sm">{t('createdBy')}: </p>
                                        <p className="text-sm mb-1.5">{dashboard.user_name}</p>
                                        <p className="text-sm">{t('createTime')}: </p>
                                        <p className="text-sm mb-1.5">{dashboard.create_time.replace('T', ' ')}</p>
                                        <p className="text-sm">{t('lastUpdateTime')}: </p>
                                        <p className="text-sm mb-1.5">{dashboard.update_time.replace('T', ' ')}</p>
                                    </div>
                                }
                                side={'bottom'}>
                                <Outlined.Info color="#999" size={16} className="cursor-pointer rotate-180" />
                            </Tip>
                        </>}
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <ButtonGroup>
                        <Button variant="outlined" size="small" onClick={handleFullscreen} color="default">{t('fullScreen')}</Button>
                        {appConfig.isDashboardPro && canEdit && <Button variant="outlined" size="small" onClick={() => publish(dashboard.id, isPublished)} color="default">{isPublished ? t('unpublish') : t('publish')}</Button>}
                        <Button variant="outlined" size="small" onClick={() => onShare(dashboard.id)} color="default">{t('share')}</Button>
                    </ButtonGroup>

                    {appConfig.isDashboardPro && <Button variant="outlined" className="disabled:pointer-events-auto" disabled={dashboard.is_default} size="small" onClick={() => onDefault(dashboard.id)} color="default">
                        {dashboard.is_default ? t('alreadyDefault') : t('setAsDefault')}
                    </Button>}

                    {appConfig.isDashboardPro && canEdit &&
                        <Tip disabled={!isPublished} content={isPublished ? t('editAfterUnpublish') : ""} side={"top"}  >
                            <Button className="disabled:pointer-events-auto" disabled={isPublished} size="small" onClick={() => onEdit(dashboard.id)}>
                                {t('editDashboard')}
                            </Button>
                        </Tip>
                    }
                </div>
            </div>

            <div id="view-panne" className="flex-1 overflow-auto">
                <EditorCanvas isPreviewMode isLoading={isLoading} />
            </div>
        </div>
    )
}
