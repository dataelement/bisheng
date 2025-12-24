"use client"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { getDashboards } from "@/controllers/API/dashboard"
import { useQuery, useQueryClient } from "react-query"
import { useNavigate, useParams } from "react-router-dom"
import { EditorCanvas } from "./components/editor/EditorCanvas"
import { EditorHeader } from "./components/editor/EditorHeader"
import { DashboardsQueryKey } from "./hook"

export default function EditorPage() {
    const navgator = useNavigate()
    const params = useParams()
    const dashboardId = params.id as string
    const { toast } = useToast()
    const queryClient = useQueryClient()

    const { data: dashboards = [] } = useQuery({
        queryKey: [DashboardsQueryKey],
        queryFn: getDashboards,
    })
    const dashboard = dashboards.find((d) => d.id === dashboardId)
    // todo api -> append dashboard 补充详情数据
    // console.log('dashboard :>> ', dashboard);

    // const handleTitleChange = (newTitle: string) => {
    //     const trimmed = newTitle.trim()

    //     if (!trimmed) {
    //         toast({
    //             description: "名称不能为空",
    //             variant: "error",
    //         })
    //         return
    //     }

    //     if (trimmed.length < 1 || trimmed.length > 200) {
    //         toast({
    //             description: "字数范围 1-200 字",
    //             variant: "error",
    //         })
    //         return
    //     }

    //     if (trimmed !== dashboard?.title) {
    //         saveMutation.mutate({ title: trimmed })
    //     }
    // }

    return (
        <div className="h-screen flex flex-col">
            <EditorHeader
                dashboard={dashboard || null}
                dashboardId={dashboardId}
            // onTitleChange={handleTitleChange}
            />

            <EditorCanvas dashboard={dashboard || null} />
        </div>
    )
}
