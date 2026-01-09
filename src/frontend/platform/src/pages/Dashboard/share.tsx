"use client"
import { getDashboard } from "@/controllers/API/dashboard"
import { useQuery } from "react-query"
import { useParams } from "react-router-dom"
import { EditorCanvas } from "./components/editor/EditorCanvas"
import { DashboardQueryKey } from "./hook"

export default function SharePage() {
    const params = useParams()
    const dashboardId = atob(params.boardId) as string

    const { data: dashboard, isLoading } = useQuery({
        queryKey: [DashboardQueryKey, dashboardId],
        queryFn: () => getDashboard(dashboardId, true),
    })

    if (dashboard?.status === "draft") {
        return <div className="size-full flex items-center justify-center">
            <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/offline.png`} alt="" />
        </div>
    }

    return (
        <div className="h-screen flex flex-col">
            <div className="h-full">
                <EditorCanvas isPreviewMode isLoading={isLoading} dashboard={dashboard || null} />
            </div>
        </div>
    )
}
