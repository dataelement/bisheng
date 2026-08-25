"use client"
import { getDashboard } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { useEffect } from "react"
import { useQuery } from "react-query"
import { useNavigate, useParams } from "react-router-dom"
import { EditorCanvas } from "./components/editor/EditorCanvas"
import { EditorHeader } from "./components/editor/EditorHeader"
import {
    DashboardQueryKey,
    useDashboardPermissions,
    useEditorShortcuts,
} from "./hook"

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
    const {
        permissions,
        loading: permissionsLoading,
        privileged,
    } = useDashboardPermissions([dashboardId])
    // A super admin never gets an action list: the hook short-circuits instead of
    // asking the backend and reports `privileged` instead. Reading the map alone
    // therefore denied every admin and bounced them to /404.
    const canEdit = privileged || (permissions[dashboardId]?.includes("edit") ?? false)

    useEffect(() => {
        if (dashboard && !permissionsLoading && !canEdit) navigate("404")
    }, [canEdit, dashboard, navigate, permissionsLoading])

    useEffect(() => {
        if (dashboard) {
            // Edit mode is synchronized only once to avoid repeated rendering 
            currentDashboard?.id !== dashboard.id && setCurrentDashboard(dashboard)
            setSelectedId(dashboard.id)
        }
    }, [dashboard, setCurrentDashboard])

    // undo redo
    useEditorShortcuts()

    if (!dashboard || isLoading || permissionsLoading || !canEdit) return null

    return (
        <div className="h-screen flex flex-col">
            <EditorHeader
                dashboard={currentDashboard}
                dashboardId={dashboardId}
            />
            <div className="h-[calc(100vh-64px-var(--license-banner-h,0px))]">
                <EditorCanvas isLoading={isLoading} />
            </div>
        </div>
    )
}
