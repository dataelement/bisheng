"use client"
import { getDashboard } from "@/controllers/API/dashboard"
import { useQuery } from "react-query"
import { useParams } from "react-router-dom"
import { EditorCanvas } from "./components/editor/EditorCanvas"
import { DashboardQueryKey } from "./hook"
import { useTranslation } from "react-i18next"
import { useEffect } from "react"
import { useEditorDashboardStore } from "@/store/dashboardStore"

export default function SharePage() {
    const params = useParams()
    const dashboardId = atob(params.boardId) as string
    const { t } = useTranslation('dashboard')
    const {
        setCurrentDashboardId: setSelectedId,
        setCurrentDashboard,
    } = useEditorDashboardStore()

    const { data: dashboard, isLoading } = useQuery({
        queryKey: [DashboardQueryKey, dashboardId],
        queryFn: () => getDashboard(dashboardId, true),
    })

    useEffect(() => {
        if (dashboard) {
            setCurrentDashboard(dashboard)
            setSelectedId(dashboard.id)
        }
    }, [dashboard, setCurrentDashboard])


    if (dashboard?.status === "draft") {
        return <div className="size-full flex flex-col items-center justify-center">
            <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/offline.png`} className="size-[400px]" alt="" />
            <p className="text-xl relative -top-16 text-center">{t('dashboardOffline')}</p>
        </div>
    }

    return (
        <div className="h-screen flex flex-col">
            <div className="h-full">
                <EditorCanvas isPreviewMode isLoading={isLoading} />
            </div>
        </div>
    )
}
