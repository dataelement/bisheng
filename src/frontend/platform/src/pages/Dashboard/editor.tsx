"use client"
import { getDashboard } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { useEffect } from "react"
import { useQuery } from "react-query"
import { useNavigate, useParams } from "react-router-dom"
import { EditorCanvas } from "./components/editor/EditorCanvas"
import { EditorHeader } from "./components/editor/EditorHeader"
import { DashboardQueryKey, useEditorShortcuts } from "./hook"

export default function EditorPage() {
    const params = useParams()
    const dashboardId = params.id as string
    const navigate = useNavigate()
    const {
        currentDashboard,
        setCurrentDashboardId: setSelectedId,
        setCurrentDashboard,
    } = useEditorDashboardStore()

    const { data: dashboard, isLoading } = useQuery({
        queryKey: [DashboardQueryKey, Number(dashboardId)],
        queryFn: () => getDashboard(dashboardId),
    })

    if (dashboard && !dashboard.write) {
        navigate("404")
    }

    useEffect(() => {
        if (dashboard) {
            // Edit mode is synchronized only once to avoid repeated rendering 
            currentDashboard?.id !== dashboard.id && setCurrentDashboard(dashboard)
            setSelectedId(dashboard.id)
        }
    }, [dashboard, setCurrentDashboard])

    // undo redo
    useEditorShortcuts()

    if (!dashboard) return null

    return (
        <div className="h-screen flex flex-col">
            <EditorHeader
                dashboard={currentDashboard}
                dashboardId={dashboardId}
            />
            <div className="h-[calc(100vh-64px)]">
                <EditorCanvas isLoading={isLoading} />
            </div>
        </div>
    )
}
