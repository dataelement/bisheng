"use client"

import { useToast } from "@/components/bs-ui/toast/use-toast"
import { locationContext } from "@/contexts/locationContext"
import {
    getDashboards,
    getShareLink,
    updateDashboard
} from "@/controllers/API/dashboard"
import { copyText } from "@/utils"
import { useContext, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { DashboardDetail } from "./components/dashboard/DashboardDetail"
import { DashboardSidebar } from "./components/dashboard/DashboardSidebar"
import { DashboardsQueryKey } from "./hook"


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
        mutationFn: ({ id, data }: { id: string; data: any }) => updateDashboard(id, data),
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



    const handleRename = (id: string, newTitle: string) => {
        const trimmed = newTitle.trim()

        if (!trimmed) {
            toast({
                description: "名称不能为空",
                variant: "error",
            })
            return
        }

        if (trimmed.length < 1 || trimmed.length > 200) {
            toast({
                description: "字数范围 1-200 字",
                variant: "error",
            })
            return
        }

        updateMutation.mutate({ id, data: { title: trimmed } })
    }


    const handleShare = async (id: string) => {
        const dashboard = dashboards.find((d) => d.id === id)

        if (dashboard?.status === "draft") {
            toast({
                description: "该看板尚未发布",
                variant: "error",
            })
            return
        }

        try {
            const link = await getShareLink(id)
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

    const selectedDashboard = dashboards.find((d) => d.id === selectedId) || null

    // Auto-select first dashboard if none selected
    if (!selectedId && dashboards.length > 0) {
        setSelectedId(dashboards[0].id)
    }

    return (
        <div className="h-screen flex">
            {appConfig.isPro && <DashboardSidebar
                dashboards={dashboards}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onRename={handleRename}
                onShare={handleShare}
            />
            }
            <DashboardDetail
                dashboard={selectedDashboard}
                onRename={handleRename}
                onShare={handleShare}
                onEdit={handleEdit}
            />
        </div>
    )
}
