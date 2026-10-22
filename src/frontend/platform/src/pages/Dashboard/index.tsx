// @ts-strict-ignore
import { notification } from '@bisheng/ui';

import { locationContext } from "@/contexts/locationContext"
import {
    getDashboard,
    getDashboards,
    setDefaultDashboard,
    updateDashboardTitle
} from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { copyText } from "@/utils"
import { useContext, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { DashboardDetail } from "./components/dashboard/DashboardDetail"
import { DashboardSidebar } from "./components/dashboard/DashboardSidebar"
import { DashboardQueryKey, DashboardsQueryKey } from "./hook"


export default function DashboardPage() {
    const { t } = useTranslation("dashboard")
    const { appConfig } = useContext(locationContext)

    const {
        currentDashboardId: selectedId,
        setCurrentDashboardId: setSelectedId,
        setCurrentDashboard,
    } = useEditorDashboardStore()

    const queryClient = useQueryClient()
    const [isCollapsed, setIsCollapsed] = useState(false)

    const { data: dashboards = [] } = useQuery({
        queryKey: [DashboardsQueryKey],
        queryFn: getDashboards,
    })

    const updateTitlteMutation = useMutation({
        mutationFn: ({ id, title }: { id: string; title: string }) => updateDashboardTitle(id, title),
        onSuccess: (a, { id, title }) => {
            // queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            // queryClient.invalidateQueries({ queryKey: [DashboardQueryKey, id] })
            queryClient.setQueryData([DashboardQueryKey, id], (old: any) => {
                old.title = title
                return old
            })
            queryClient.setQueryData([DashboardsQueryKey], (old: any) =>
                old.map(el => el.id === id ? { ...el, title } : el));
            notification.open({ type: "success", description: String(t('renameSuccess') ?? '') })
        },
        onError: () => {
            notification.open({ type: "error", description: String(t('renameError') ?? '') })
        },
    })

    const setDefaultMutation = useMutation({
        mutationFn: (id: string) => setDefaultDashboard(id),
        onSuccess: (a, id) => {
            // queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            queryClient.setQueryData([DashboardsQueryKey], (old) =>
                old.map(el => ({ ...el, is_default: el.id === id })));
            queryClient.invalidateQueries({ queryKey: [DashboardQueryKey, id] })
        },
        onError: () => {
        }
    })

    const handleRename = (id: string, newTitle: string) => {
        updateTitlteMutation.mutate({ id, title: newTitle })
    }

    const handleShare = async (id: string) => {
        // const _selectedDashboard = dashboards.find((d) => d.id === id)
        if (selectedDashboard?.status === "draft") {
            notification.open({ type: "error", description: String(t('shareNotPublished') ?? '') })
            return
        }

        try {
            const link = `${location.origin}${__APP_ENV__.BASE_URL}/dashboard/share/${btoa(selectedDashboard.id)}`
            await copyText(link)
            notification.open({ type: "success", description: String(t('shareCopySuccess') ?? '') })
        } catch (error) {
            notification.open({ type: "error", description: String(t('shareCopyError') ?? '') })
        }
    }

    const navigator = useNavigate()
    const handleEdit = (id: string) => {
        navigator(`/dashboard/${id}`)
    }

    const { data: selectedDashboard, isInitialLoading: isLoading } = useQuery({
        queryKey: [DashboardQueryKey, selectedId],
        queryFn: () => getDashboard(selectedId),
        enabled: !!selectedId,
    })

    useEffect(() => {
        return () => setSelectedId("")
    }, [])

    // dashboard reactquery to store
    useEffect(() => {
        if (selectedDashboard) {
            setCurrentDashboard(selectedDashboard)
            setSelectedId(selectedDashboard.id)
        }
    }, [selectedDashboard, setCurrentDashboard])

    // Auto-select first dashboard if none selected
    if (!selectedId && dashboards.length > 0) {
        const defaultDashboard = dashboards.find((d) => d.is_default)
        setSelectedId(defaultDashboard?.id || dashboards[0].id)
    }

    return (
        <div className="h-full flex">
            {appConfig.isDashboardPro && <DashboardSidebar
                isCollapsed={isCollapsed}
                setIsCollapsed={setIsCollapsed}
                dashboards={dashboards}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onRename={handleRename}
                onDefault={(id) => setDefaultMutation.mutate(id)}
                onShare={handleShare}
            />
            }
            <DashboardDetail
                isCollapsed={isCollapsed}
                setIsCollapsed={setIsCollapsed}
                dashboard={selectedDashboard}
                isLoading={isLoading}
                onRename={handleRename}
                onDefault={(id) => setDefaultMutation.mutate(id)}
                onShare={handleShare}
                onEdit={handleEdit}
            />
        </div>
    )
}
