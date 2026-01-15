"use client"
import { getDashboard } from "@/controllers/API/dashboard"
import { useQuery } from "react-query"
import { useNavigate, useParams } from "react-router-dom"
import { EditorCanvas } from "./components/editor/EditorCanvas"
import { EditorHeader } from "./components/editor/EditorHeader"
import { DashboardQueryKey, useEditorShortcuts } from "./hook"

export default function EditorPage() {
    const params = useParams()
    const dashboardId = params.id as string
    const navigate = useNavigate()

    const { data: dashboard, isLoading } = useQuery({
        queryKey: [DashboardQueryKey, Number(dashboardId)],
        queryFn: () => getDashboard(dashboardId),
    })

    if (dashboard && !dashboard.write) {
        navigate("404")
    }

    // undo redo
    useEditorShortcuts()

    if (!dashboard) return null

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
