"use client"
import { getDashboard } from "@/controllers/API/dashboard"
import { useQuery } from "react-query"
import { useParams } from "react-router-dom"
import { EditorCanvas } from "./components/editor/EditorCanvas"
import { EditorHeader } from "./components/editor/EditorHeader"
import { DashboardQueryKey } from "./hook"

export default function EditorPage() {
    const params = useParams()
    const dashboardId = params.id as string

    const { data: dashboard, isLoading } = useQuery({
        queryKey: [DashboardQueryKey, dashboardId],
        queryFn: () => getDashboard(dashboardId),
    })

    return (
        <div className="h-screen flex flex-col">
            <EditorHeader
                dashboard={dashboard || null}
                dashboardId={dashboardId}
            />
            <div className="h-[calc(100vh-64px)]">
                <EditorCanvas isLoading={isLoading} dashboard={dashboard || null} />
            </div>
        </div>
    )
}
