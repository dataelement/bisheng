"use client"

import { useToast } from "@/components/bs-ui/toast/use-toast"
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
import { useMutation, useQuery, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { DashboardDetail } from "./components/dashboard/DashboardDetail"
import { DashboardSidebar } from "./components/dashboard/DashboardSidebar"
import { DashboardQueryKey, DashboardsQueryKey } from "./hook"


export default function DashboardPage() {
    const { t } = useTranslation("dashboard")
    const { appConfig } = useContext(locationContext)
    const [selectedId, setSelectedId] = useEditorDashboardStore(state => [state.currentDashboardId, state.setCurrentDashboardId])
    const { toast } = useToast()
    const queryClient = useQueryClient()
    const [isCollapsed, setIsCollapsed] = useState(false)

    const { data: dashboards = [] } = useQuery({
        queryKey: [DashboardsQueryKey],
        queryFn: getDashboards,
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, title }: { id: string; title: string }) => updateDashboardTitle(id, title),
        onSuccess: (a, { id, title }) => {
            // queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            queryClient.invalidateQueries({ queryKey: [DashboardQueryKey, id] })
            queryClient.setQueryData([DashboardsQueryKey], (old) =>
                old.map(el => el.id === id ? { ...el, title } : el));
            toast({
                description: t('renameSuccess'),
                variant: "success",
            })
        },
        onError: () => {
            toast({
                description: t('renameError'),
                variant: "error",
            })
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
        updateMutation.mutate({ id, title: newTitle })
    }

    const handleShare = async (id: string) => {
        // const _selectedDashboard = dashboards.find((d) => d.id === id)
        if (selectedDashboard?.status === "draft") {
            toast({
                description: t('shareNotPublished'),
                variant: "error",
            })
            return
        }

        try {
            const link = `${location.origin}${__APP_ENV__.BASE_URL}/dashboard/share/${btoa(selectedDashboard.id)}`
            await copyText(link)
            toast({
                description: t('shareCopySuccess'),
                variant: "success",
            })
        } catch (error) {
            toast({
                description: t('shareCopyError'),
                variant: "error",
            })
        }
    }

    const navigator = useNavigate()
    const handleEdit = (id: string) => {
        navigator(`/dashboard/${id}`)
    }

    const { data: selectedDashboard, isLoading } = useQuery({
        queryKey: [DashboardQueryKey, selectedId],
        queryFn: () => getDashboard(selectedId),
        enabled: !!selectedId,
    })

    useEffect(() => {
        return () => setSelectedId("")
    }, [])

    // Auto-select first dashboard if none selected
    if (!selectedId && dashboards.length > 0) {
        const defaultDashboard = dashboards.find((d) => d.is_default)
        setSelectedId(defaultDashboard?.id || dashboards[0].id)
    }

    return (
        <div className="h-full flex">
            {appConfig.isPro && <DashboardSidebar
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
