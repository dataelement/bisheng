"use client"

import { useToast } from "@/components/bs-ui/toast/use-toast"
import { locationContext } from "@/contexts/locationContext"
import {
    getDashboard,
    getDashboards,
    getShareLink,
    setDefaultDashboard,
    updateDashboard,
    updateDashboardTitle
} from "@/controllers/API/dashboard"
import { copyText } from "@/utils"
import { useContext, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { DashboardDetail } from "./components/dashboard/DashboardDetail"
import { DashboardSidebar } from "./components/dashboard/DashboardSidebar"
import { DashboardQueryKey, DashboardsQueryKey } from "./hook"


export default function DashboardPage() {
    const { appConfig } = useContext(locationContext)
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const { toast } = useToast()
    const queryClient = useQueryClient()

    const { data: dashboards = [] } = useQuery({
        queryKey: [DashboardsQueryKey],
        queryFn: getDashboards,
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, title }: { id: string; title: string }) => updateDashboardTitle(id, title),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            toast({
                description: "已重命名",
                variant: "success",
            })
        },
        onError: () => {
            toast({
                description: "重命名失败",
                variant: "error",
            })
        },
    })

    const setDefaultMutation = useMutation({
        mutationFn: (id: string) => setDefaultDashboard(id),
        onSuccess: (a, id) => {
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            queryClient.invalidateQueries({ queryKey: [DashboardQueryKey, id] })
        },
        onError: () => {
        }
    })



    const handleRename = (id: string, newTitle: string) => {
        updateMutation.mutate({ id, title: newTitle })
    }


    const handleShare = async (id: string) => {
        if (selectedDashboard?.status === "draft") {
            toast({
                description: "该看板尚未发布",
                variant: "error",
            })
            return
        }

        try {
            const link = `${location.origin}${__APP_ENV__.BASE_URL}/dashboard/share/${btoa(selectedDashboard.id)}`
            await copyText(link)
            toast({
                description: "分享链接已复制",
                variant: "success",
            })
        } catch (error) {
            toast({
                description: "复制失败",
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
    })

    // Auto-select first dashboard if none selected
    if (!selectedId && dashboards.length > 0) {
        const defaultDashboard = dashboards.find((d) => d.is_default)
        setSelectedId(defaultDashboard?.id || dashboards[0].id)
    }

    return (
        <div className="h-full flex">
            {appConfig.isPro && <DashboardSidebar
                dashboards={dashboards}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onRename={handleRename}
                onDefault={(id) => setDefaultMutation.mutate(id)}
                onShare={handleShare}
            />
            }
            <DashboardDetail
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
